# -*- coding: utf-8 -*-
"""
Unit tests for the Deis api app.

Run the tests with "./manage.py test api"
"""
import json

from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APITransactionTestCase
from unittest import mock
from rest_framework.authtoken.models import Token

from api.models import App, Config

from . import adapter
from . import mock_port
import requests_mock


@requests_mock.Mocker(real_http=True, adapter=adapter)
@mock.patch('api.models.release.publish_release', lambda *args: None)
@mock.patch('api.models.release.docker_get_port', mock_port)
class ConfigTest(APITransactionTestCase):

    """Tests setting and updating config values"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = Token.objects.get(user=self.user).key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

        url = '/v2/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201, response.data)
        self.app = App.objects.all()[0]

    def tearDown(self):
        # make sure every test has a clean slate for k8s mocking
        cache.clear()

    def test_config(self, mock_requests):
        """
        Test that config is auto-created for a new app and that
        config can be updated using a PATCH
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # check to see that an initial/empty config was created
        url = "/v2/apps/{app_id}/config".format(**locals())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('values', response.data)
        self.assertEqual(response.data['values'], {})
        config1 = response.data

        # set an initial config value
        body = {'values': json.dumps({'NEW_URL1': 'http://localhost:8080/'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        config2 = response.data
        self.assertNotEqual(config1['uuid'], config2['uuid'])
        self.assertIn('NEW_URL1', response.data['values'])

        # read the config
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        config3 = response.data
        self.assertEqual(config2, config3)
        self.assertIn('NEW_URL1', response.data['values'])

        # set an additional config value
        body = {'values': json.dumps({'NEW_URL2': 'http://localhost:8080/'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        config3 = response.data
        self.assertNotEqual(config2['uuid'], config3['uuid'])
        self.assertIn('NEW_URL1', response.data['values'])
        self.assertIn('NEW_URL2', response.data['values'])

        # read the config again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        config4 = response.data
        self.assertEqual(config3, config4)
        self.assertIn('NEW_URL1', response.data['values'])
        self.assertIn('NEW_URL2', response.data['values'])

        # unset a config value
        body = {'values': json.dumps({'NEW_URL2': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        config5 = response.data
        self.assertNotEqual(config4['uuid'], config5['uuid'])
        self.assertNotIn('NEW_URL2', json.dumps(response.data['values']))

        # unset all config values
        body = {'values': json.dumps({'NEW_URL1': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('NEW_URL1', json.dumps(response.data['values']))

        # set a port and then unset it to make sure validation ignores the unset
        body = {'values': json.dumps({'PORT': '5000'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('PORT', response.data['values'])

        body = {'values': json.dumps({'PORT': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('PORT', response.data['values'])

        # disallow put/patch/delete
        response = self.client.put(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.patch(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405, response.data)
        return config5

    def test_response_data(self, mock_requests):
        """Test that the serialized response contains only relevant data."""
        body = {'id': 'test'}
        response = self.client.post('/v2/apps', body)
        url = "/v2/apps/test/config"

        # set an initial config value
        body = {'values': json.dumps({'PORT': '5000'})}
        response = self.client.post(url, body)
        for key in response.data:
            self.assertIn(key, ['uuid', 'owner', 'created', 'updated', 'app', 'values', 'memory',
                                'cpu', 'tags', 'registry'])
        expected = {
            'owner': self.user.username,
            'app': 'test',
            'values': {'PORT': '5000'},
            'memory': {},
            'cpu': {},
            'tags': {},
            'registry': {}
        }
        self.assertDictContainsSubset(expected, response.data)

    def test_response_data_types_converted(self, mock_requests):
        """Test that config data is converted into the correct type."""
        body = {'id': 'test'}
        response = self.client.post('/v2/apps', body)
        url = "/v2/apps/test/config"

        body = {'values': json.dumps({'PORT': 5000}), 'cpu': json.dumps({'web': '1024'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        for key in response.data:
            self.assertIn(key, ['uuid', 'owner', 'created', 'updated', 'app', 'values', 'memory',
                                'cpu', 'tags', 'registry'])
        expected = {
            'owner': self.user.username,
            'app': 'test',
            'values': {'PORT': '5000'},
            'memory': {},
            'cpu': {'web': "1024"},
            'tags': {},
            'registry': {}
        }
        self.assertDictContainsSubset(expected, response.data)

        body = {'cpu': json.dumps({'web': 'this will fail'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('CPU shares must be a numeric value', response.data['cpu'])

    def test_config_set_same_key(self, mock_requests):
        """
        Test that config sets on the same key function properly
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = "/v2/apps/{app_id}/config".format(**locals())

        # set an initial config value
        body = {'values': json.dumps({'PORT': '5000'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('PORT', response.data['values'])

        # reset same config value
        body = {'values': json.dumps({'PORT': '5001'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('PORT', response.data['values'])
        self.assertEqual(response.data['values']['PORT'], '5001')

    def test_config_set_unicode(self, mock_requests):
        """
        Test that config sets with unicode values are accepted.
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = "/v2/apps/{app_id}/config".format(**locals())

        # set an initial config value
        body = {'values': json.dumps({'POWERED_BY': 'Деис'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('POWERED_BY', response.data['values'])
        # reset same config value
        body = {'values': json.dumps({'POWERED_BY': 'Кроликов'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('POWERED_BY', response.data['values'])
        self.assertEqual(response.data['values']['POWERED_BY'], 'Кроликов')

        # set an integer to test unicode regression
        body = {'values': json.dumps({'INTEGER': 1})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('INTEGER', response.data['values'])
        self.assertEqual(response.data['values']['INTEGER'], '1')

    def test_config_str(self, mock_requests):
        """Test the text representation of a node."""
        config5 = self.test_config()
        config = Config.objects.get(uuid=config5['uuid'])
        self.assertEqual(str(config), "{}-{}".format(config5['app'], str(config5['uuid'])[:7]))

    def test_valid_config_keys(self, mock_requests):
        """Test that valid config keys are accepted.
        """
        keys = ("FOO", "_foo", "f001", "FOO_BAR_BAZ_")
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = '/v2/apps/{app_id}/config'.format(**locals())
        for k in keys:
            body = {'values': json.dumps({k: "testvalue"})}
            resp = self.client.post(url, body)
            self.assertEqual(resp.status_code, 201)
            self.assertIn(k, resp.data['values'])

    def test_config_deploy_failure(self, mock_requests):
        """
        Cause an Exception in app.deploy to cause a release.delete
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # deploy app to get a build
        url = "/v2/apps/{}/builds".format(app_id)
        body = {'image': 'autotest/example'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['image'], body['image'])

        with mock.patch('api.models.App.deploy') as mock_deploy:
            mock_deploy.side_effect = Exception('Boom!')
            url = '/v2/apps/{app_id}/config'.format(**locals())
            body = {'values': json.dumps({'test': "testvalue"})}
            resp = self.client.post(url, body)
            self.assertEqual(resp.status_code, 400)

    def test_invalid_config_keys(self, mock_requests):
        """Test that invalid config keys are rejected.
        """
        keys = ("123", "../../foo", "FOO/", "FOO-BAR")
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = '/v2/apps/{app_id}/config'.format(**locals())
        for k in keys:
            body = {'values': json.dumps({k: "testvalue"})}
            resp = self.client.post(url, body)
            self.assertEqual(resp.status_code, 400)

    def test_invalid_config_values(self, mock_requests):
        """
        Test that invalid config values are rejected.
        Right now only PORT is checked
        """
        data = [
            {'field': 'PORT', 'value': 'dog'},
            {'field': 'PORT', 'value': 99999}
        ]
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = '/v2/apps/{app_id}/config'.format(**locals())
        for row in data:
            body = {'values': json.dumps({row['field']: row['value']})}
            resp = self.client.post(url, body)
            self.assertEqual(resp.status_code, 400, response.data)

    def test_admin_can_create_config_on_other_apps(self, mock_requests):
        """If a non-admin creates an app, an administrator should be able to set config
        values for that app.
        """
        user = User.objects.get(username='autotest2')
        token = Token.objects.get(user=user).key
        url = '/v2/apps'
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = "/v2/apps/{app_id}/config".format(**locals())

        # set an initial config value
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        body = {'values': json.dumps({'PORT': '5000'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('PORT', response.data['values'])
        return response

    def test_limit_memory(self, mock_requests):
        """
        Test that limit is auto-created for a new app and that
        limits can be updated using a PATCH
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = '/v2/apps/{app_id}/config'.format(**locals())

        # check default limit
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('memory', response.data)
        self.assertEqual(response.data['memory'], {})
        # regression test for https://github.com/deis/deis/issues/1563
        self.assertNotIn('"', response.data['memory'])

        # set an initial limit
        mem = {'web': '1G'}
        body = {'memory': json.dumps(mem)}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        limit1 = response.data

        # check memory limits
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('memory', response.data)
        memory = response.data['memory']
        self.assertIn('web', memory)
        self.assertEqual(memory['web'], '1G')

        # set an additional value
        body = {'memory': json.dumps({'worker': '512M'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        limit2 = response.data
        self.assertNotEqual(limit1['uuid'], limit2['uuid'])
        memory = response.data['memory']
        self.assertIn('worker', memory)
        self.assertEqual(memory['worker'], '512M')
        self.assertIn('web', memory)
        self.assertEqual(memory['web'], '1G')

        # read the limit again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        limit3 = response.data
        self.assertEqual(limit2, limit3)
        memory = response.data['memory']
        self.assertIn('worker', memory)
        self.assertEqual(memory['worker'], '512M')
        self.assertIn('web', memory)
        self.assertEqual(memory['web'], '1G')

        # regression test for https://github.com/deis/deis/issues/1613
        # ensure that config:set doesn't wipe out previous limits
        body = {'values': json.dumps({'NEW_URL2': 'http://localhost:8080/'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('NEW_URL2', response.data['values'])

        # read the limit again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        memory = response.data['memory']
        self.assertIn('worker', memory)
        self.assertEqual(memory['worker'], '512M')
        self.assertIn('web', memory)
        self.assertEqual(memory['web'], '1G')

        # unset a value
        body = {'memory': json.dumps({'worker': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        limit4 = response.data
        self.assertNotEqual(limit3['uuid'], limit4['uuid'])
        self.assertNotIn('worker', json.dumps(response.data['memory']))

        # bad memory values
        mem = {'web': '1Z'}
        body = {'memory': json.dumps(mem)}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        mem = {'w3&b': '1G'}
        body = {'memory': json.dumps(mem)}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        # disallow put/patch/delete
        response = self.client.put(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.patch(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405, response.data)
        return limit4

    def test_limit_cpu(self, mock_requests):
        """
        Test that CPU limits can be set
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']
        url = '/v2/apps/{app_id}/config'.format(**locals())

        # check default limit
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('cpu', response.data)
        self.assertEqual(response.data['cpu'], {})
        # regression test for https://github.com/deis/deis/issues/1563
        self.assertNotIn('"', response.data['cpu'])

        # set an initial limit
        body = {'cpu': json.dumps({'web': '1024'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        limit1 = response.data

        # check memory limits
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('cpu', response.data)
        cpu = response.data['cpu']
        self.assertIn('web', cpu)
        self.assertEqual(cpu['web'], '1024')

        # set an additional value
        body = {'cpu': json.dumps({'worker': '512m'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        limit2 = response.data
        self.assertNotEqual(limit1['uuid'], limit2['uuid'])
        cpu = response.data['cpu']
        self.assertIn('worker', cpu)
        self.assertEqual(cpu['worker'], '512m')
        self.assertIn('web', cpu)
        self.assertEqual(cpu['web'], '1024')

        # read the limit again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        limit3 = response.data
        self.assertEqual(limit2, limit3)
        cpu = response.data['cpu']
        self.assertIn('worker', cpu)
        self.assertEqual(cpu['worker'], '512m')
        self.assertIn('web', cpu)
        self.assertEqual(cpu['web'], '1024')

        # unset a value
        body = {'cpu': json.dumps({'worker': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        limit4 = response.data
        self.assertNotEqual(limit3['uuid'], limit4['uuid'])
        self.assertNotIn('worker', json.dumps(response.data['cpu']))

        # bad cpu values
        mem = {'web': '1G'}
        body = {'cpu': json.dumps(mem)}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        mem = {'w3&b': '1G'}
        body = {'cpu': json.dumps(mem)}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        # disallow put/patch/delete
        response = self.client.put(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.patch(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405, response.data)
        return limit4

    def test_tags(self, mock_requests):
        """
        Test that tags can be set on an application
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # check default
        url = '/v2/apps/{app_id}/config'.format(**locals())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('tags', response.data)
        self.assertEqual(response.data['tags'], {})

        # set some tags
        body = {'tags': json.dumps({'environ': 'dev'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        tags1 = response.data

        # check tags again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('tags', response.data)
        tags = response.data['tags']
        self.assertIn('environ', tags)
        self.assertEqual(tags['environ'], 'dev')

        # set an additional value
        body = {'tags': json.dumps({'rack': '1'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        tags2 = response.data
        self.assertNotEqual(tags1['uuid'], tags2['uuid'])
        tags = response.data['tags']
        self.assertIn('rack', tags)
        self.assertEqual(tags['rack'], '1')
        self.assertIn('environ', tags)
        self.assertEqual(tags['environ'], 'dev')

        # read the limit again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        tags3 = response.data
        self.assertEqual(tags2, tags3)
        tags = response.data['tags']
        self.assertIn('rack', tags)
        self.assertEqual(tags['rack'], '1')
        self.assertIn('environ', tags)
        self.assertEqual(tags['environ'], 'dev')

        # unset a value
        body = {'tags': json.dumps({'rack': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        tags4 = response.data
        self.assertNotEqual(tags3['uuid'], tags4['uuid'])
        self.assertNotIn('rack', json.dumps(response.data['tags']))

        # set valid values
        body = {'tags': json.dumps({'kubernetes.io/hostname': '172.17.8.100'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        body = {'tags': json.dumps({'is.valid': 'is-also_valid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        body = {'tags': json.dumps({'host.the-name.com/is.valid': 'valid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        body = {'tags': json.dumps({'host.the-name.com/does.no.exist': 'valid'})}
        response = self.client.post(url, body)
        self.assertContains(
            response,
            'Addition of host.the-name.com/does.no.exist=valid is the cause',
            status_code=400
        )

        # set invalid values
        body = {'tags': json.dumps({'valid': 'in\nvalid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        body = {'tags': json.dumps({'host.name.com/notvalid-': 'valid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        body = {'tags': json.dumps({'valid': 'invalid.'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        body = {'tags': json.dumps({'host.name.com/,not.valid': 'valid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        long_tag = 'a' * 300
        body = {'tags': json.dumps({'{}/not.valid'.format(long_tag): 'valid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        body = {'tags': json.dumps({'this&foo.com/not.valid': 'valid'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        # disallow put/patch/delete
        response = self.client.put(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.patch(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405, response.data)

    def test_registry(self, mock_requests):
        """
        Test that registry information can be set on an application
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # check default
        url = '/v2/apps/{app_id}/config'.format(**locals())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('registry', response.data)
        self.assertEqual(response.data['registry'], {})

        # set some registry information without PORT
        body = {'registry': json.dumps({'username': 'bob'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        registry1 = response.data

        # set required PORT
        body = {'values': json.dumps({'PORT': '80'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        registry1 = response.data

        # set some registry information
        body = {'registry': json.dumps({'username': 'bob'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        registry1 = response.data

        # check registry information again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('registry', response.data)
        registry = response.data['registry']
        self.assertIn('username', registry)
        self.assertEqual(registry['username'], 'bob')

        # set an additional value
        # set them upper case, internally it should translate to lower
        body = {'registry': json.dumps({'PASSWORD': 's3cur3pw1'})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        registry2 = response.data
        self.assertNotEqual(registry1['uuid'], registry2['uuid'])
        registry = response.data['registry']
        self.assertIn('password', registry)
        self.assertEqual(registry['password'], 's3cur3pw1')
        self.assertIn('username', registry)
        self.assertEqual(registry['username'], 'bob')

        # read the registry information again
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        registry3 = response.data
        self.assertEqual(registry2, registry3)
        registry = response.data['registry']
        self.assertIn('password', registry)
        self.assertEqual(registry['password'], 's3cur3pw1')
        self.assertIn('username', registry)
        self.assertEqual(registry['username'], 'bob')

        # unset a value
        body = {'registry': json.dumps({'password': None})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        registry4 = response.data
        self.assertNotEqual(registry3['uuid'], registry4['uuid'])
        self.assertNotIn('password', json.dumps(response.data['registry']))

        # bad registry key values
        body = {'registry': json.dumps({'pa$$w0rd': 'woop'})}
        response = self.client.post(url, body)
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        # disallow put/patch/delete
        response = self.client.put(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.patch(url)
        self.assertEqual(response.status_code, 405, response.data)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405, response.data)

    def test_registry_deploy(self, mock_requests):
        """
        Test that registry information can be applied
        """
        url = '/v2/apps'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # Set mandatory PORT
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'PORT': '4999'})}
        )

        # Set registry information
        body = {'registry': json.dumps({
            'username': 'bob',
            'password': 's3cur3pw1'
        })}
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            body
        )
        self.assertEqual(resp.status_code, 201, response.data)
        self.assertIn('username', resp.data['registry'])
        self.assertIn('password', resp.data['registry'])
        self.assertEqual(resp.data['registry']['username'], 'bob')
        self.assertEqual(resp.data['registry']['password'], 's3cur3pw1')

        # post a new build
        url = "/v2/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

    def test_config_owner_is_requesting_user(self, mock_requests):
        """
        Ensure that setting the config value is owned by the requesting user
        See https://github.com/deis/deis/issues/2650
        """
        response = self.test_admin_can_create_config_on_other_apps()
        self.assertEqual(response.data['owner'], self.user.username)

    def test_unauthorized_user_cannot_modify_config(self, mock_requests):
        """
        An unauthorized user should not be able to modify other config.

        Since an unauthorized user can't access the application, these
        requests should return a 403.
        """
        app_id = 'autotest'
        base_url = '/v2/apps'
        body = {'id': app_id}
        response = self.client.post(base_url, body)

        unauthorized_user = User.objects.get(username='autotest2')
        unauthorized_token = Token.objects.get(user=unauthorized_user).key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + unauthorized_token)
        url = '{}/{}/config'.format(base_url, app_id)
        body = {'values': {'FOO': 'bar'}}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

    def test_healthchecks(self, mock_requests):
        """
        Test that healthchecks can be applied
        """
        response = self.client.post('/v2/apps')
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # Set a healthcheck option before URL is around (URL is required for full setting)
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_INITIAL_DELAY': '25'})}
        )
        self.assertEqual(resp.status_code, 201, response.data)
        self.assertIn('HEALTHCHECK_INITIAL_DELAY', resp.data['values'])
        self.assertEqual(resp.data['values']['HEALTHCHECK_INITIAL_DELAY'], '25')

        # Set healthcheck URL to get defaults set
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_URL': '/health'})}
        )
        self.assertEqual(resp.status_code, 201, response.data)
        self.assertIn('HEALTHCHECK_URL', resp.data['values'])
        self.assertEqual(resp.data['values']['HEALTHCHECK_URL'], '/health')

        # post a new build
        response = self.client.post(
            "/v2/apps/{app_id}/builds".format(**locals()),
            {'image': 'quay.io/autotest/example'}
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_healthchecks_validations(self, mock_requests):
        """
        Test that healthchecks validations work
        """
        response = self.client.post('/v2/apps')
        self.assertEqual(response.status_code, 201, response.data)
        app_id = response.data['id']

        # Set one of the values that require a numeric value to a string
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_INITIAL_DELAY': 'horse'})}
        )
        self.assertEqual(resp.status_code, 400, response.data)

        # test URL - Path is the only allowed thing
        # Try setting various things such as query param

        # query param
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_URL': '/health?testing=0'})}
        )
        self.assertEqual(resp.status_code, 400, response.data)

        # fragment
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_URL': '/health#db'})}
        )
        self.assertEqual(resp.status_code, 400, response.data)

        # netloc
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_URL': 'http://someurl.com/health/'})}
        )
        self.assertEqual(resp.status_code, 400, response.data)

        # no path
        resp = self.client.post(
            '/v2/apps/{app_id}/config'.format(**locals()),
            {'values': json.dumps({'HEALTHCHECK_URL': 'http://someurl.com'})}
        )
        self.assertEqual(resp.status_code, 400, response.data)
