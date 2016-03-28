"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""

import os
import shutil
import subprocess
import tempfile

from mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings as _override_settings
from django.utils.six import StringIO
from django.utils.six.moves import reload_module

from django_ca import ca_settings
from django_ca.models import CertificateAuthority


class override_settings(_override_settings):
    """Enhance override_settings to also reload django_ca.ca_settings.

    .. WARNING:: When using this class as a class decorator, the decorated class must inherit from
       :py:class:`~django_ca.tests.base.DjangoCATestCase`.
    """

    def __call__(self, test_func):
        if isinstance(test_func, type) and not issubclass(test_func, DjangoCATestCase):
            raise Exception("Only subclasses of DjangoCATestCase can use override_settings.")
        inner = super(override_settings, self).__call__(test_func)
        return inner

    def save_options(self, test_func):
        super(override_settings, self).save_options(test_func)
        reload_module(ca_settings)

    def enable(self):
        super(override_settings, self).enable()
        reload_module(ca_settings)

    def disable(self):
        super(override_settings, self).disable()
        reload_module(ca_settings)


class override_tmpcadir(override_settings):
    """Sets the CA_DIR directory to a temporary directory.

    .. NOTE: This also takes any additional settings.
    """

    def __init__(self, **kwargs):
        super(override_tmpcadir, self).__init__(**kwargs)
        self.options['CA_DIR'] = tempfile.mkdtemp()

    def disable(self):
        super(override_tmpcadir, self).disable()
        shutil.rmtree(self.options['CA_DIR'])


class DjangoCATestCase(TestCase):
    """Base class for all testcases with some enhancements."""

    @classmethod
    def setUpClass(cls):
        super(DjangoCATestCase, cls).setUpClass()

        if cls._overridden_settings:
            reload_module(ca_settings)

    @classmethod
    def tearDownClass(cls):
        overridden = False
        ca_dir = None
        if hasattr(cls, '_cls_overridden_context'):
            overridden = True
            ca_dir = cls._cls_overridden_context.options.get('CA_DIR')

        super(DjangoCATestCase, cls).tearDownClass()

        if overridden is True:
            reload_module(ca_settings)
            if ca_dir is not None:
                shutil.rmtree(ca_dir)


    def setUp(self):
        reload_module(ca_settings)

    def settings(self, **kwargs):
        return override_settings(**kwargs)

    def tmpcadir(self, **kwargs):
        return override_tmpcadir(**kwargs)

    def assertSubject(self, cert, expected):
        actual = cert.get_subject().get_components()
        actual = [(k.decode('utf-8'), v.decode('utf-8')) for k, v in actual]
        self.assertEqual(actual, expected)

    @classmethod
    def init_ca(cls, **kwargs):
        kwargs.setdefault('key_size', ca_settings.CA_MIN_KEY_SIZE)
        return CertificateAuthority.objects.init(
            name='Root CA', key_type='RSA', algorithm='sha256', expires=720, parent=None, pathlen=0,
            subject={'CN': 'ca.example.com', }, **kwargs)

    @classmethod
    def create_csr(cls, name='example.com', key_size=512):
        key = os.path.join(ca_settings.CA_DIR, '%s.key' % name)
        csr = os.path.join(ca_settings.CA_DIR, '%s.csr' % name)
        subj = '/C=AT/ST=Vienna/L=Vienna/CN=csr.%s' % name

        p1 = subprocess.Popen(['openssl', 'genrsa', '-out', key, str(key_size)],
                              stderr=subprocess.PIPE)
        p1.communicate()
        p2 = subprocess.Popen(['openssl', 'req', '-new', '-key', key, '-out', csr, '-utf8',
                               '-batch', '-subj', '%s' % subj])
        p2.communicate()
        return key, csr

    @classmethod
    def get_subject(cls, x509):
        return {k.decode('utf-8'): v.decode('utf-8') for k, v
                in x509.get_subject().get_components()}

    @classmethod
    def get_extensions(cls, x509):
        exts = [x509.get_extension(i) for i in range(0, x509.get_extension_count())]
        return {ext.get_short_name().decode('utf-8'): str(ext) for ext in exts}

    @classmethod
    def get_alt_names(cls, x509):
        return [n.strip() for n in cls.get_extensions(x509)['subjectAltName'].split(',')]

    def assertParserError(self, args, expected):
        """Assert that given args throw a parser error."""

        buf = StringIO()
        with self.assertRaises(SystemExit), patch('sys.stderr', buf):
            self.parser.parse_args(args)

        output = buf.getvalue()
        self.assertEqual(output, expected)
        return output

    def cmd(self, *args, **kwargs):
        kwargs['stdout'] = StringIO()
        kwargs['stderr'] = StringIO()
        call_command(*args, **kwargs)
        return kwargs['stdout'].getvalue(), kwargs['stderr'].getvalue()


@override_settings(CA_MIN_KEY_SIZE=512)
class DjangoCAWithCATestCase(DjangoCATestCase):
    """A test class that already has a CA predefined."""

    @classmethod
    def setUpClass(cls):
        super(DjangoCAWithCATestCase, cls).setUpClass()
        cls.ca = cls.init_ca()


class DjangoCAWithCSRTestCase(DjangoCAWithCATestCase):
    @classmethod
    def setUpClass(cls):
        super(DjangoCAWithCSRTestCase, cls).setUpClass()

        key, csr = cls.create_csr()
        cls.csr_path = csr
        with open(csr, 'rb') as csr_stream:
            cls.csr = csr_stream.read()
