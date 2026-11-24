import unittest
import uuid

from main import DatabaseManager


class LinksPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()

    def _base_client(self, username):
        return {
            'username': username,
            'company_name': 'Cliente Test',
            'bio': 'Perfil de prueba',
            'category': 'abogados',
            'final_url': 'https://ejemplo.com/tarjeta/',
            'logo_path': '',
            'catalog_pdf_path': '',
            'contact_email': '',
            'contact_phone': '',
            'primary_website': '',
            'full_name': '',
            'job_title': '',
            'secondary_email': '',
            'secondary_phone': '',
            'physical_address': '',
            'primary_instagram': '',
            'primary_linkedin': '',
            'links': [],
        }

    def test_updates_existing_client_links(self):
        username = f"test-update-{uuid.uuid4().hex[:8]}"
        first = self._base_client(username)
        first['primary_website'] = 'https://uno.com'
        first['links'] = [
            {'name': 'WhatsApp', 'url': '1111111111', 'active': True},
        ]

        second = self._base_client(username)
        second['primary_website'] = 'https://dos.com'
        second['links'] = [
            {'name': 'WhatsApp', 'url': '2222222222', 'active': True},
            {'name': 'GitHub', 'url': 'https://github.com/dos', 'active': True},
        ]

        self.assertTrue(self.db.save_client(first))
        self.assertTrue(self.db.save_client(second))

        client = self.db.get_client_by_username(username)
        self.assertIsNotNone(client)
        self.assertEqual(client['primary_website'], 'https://dos.com')

        link_map = {item['name']: item['url'] for item in client['links']}
        self.assertEqual(link_map['WhatsApp'], '2222222222')
        self.assertEqual(link_map['GitHub'], 'https://github.com/dos')
        self.assertEqual(link_map['Sitio Web'], 'https://dos.com')

    def test_restores_contact_email_from_special_link(self):
        username = f"test-email-{uuid.uuid4().hex[:8]}"
        data = self._base_client(username)
        data['contact_email'] = 'hola@empresa.com'
        data['links'] = [
            {'name': 'Instagram', 'url': 'https://instagram.com/empresa', 'active': True},
        ]

        self.assertTrue(self.db.save_client(data))

        client = self.db.get_client_by_username(username)
        self.assertIsNotNone(client)
        self.assertEqual(client['contact_email'], 'hola@empresa.com')

        link_map = {item['name']: item['url'] for item in client['links']}
        self.assertEqual(link_map['Correo electrónico'], 'hola@empresa.com')
        self.assertEqual(link_map['Instagram'], 'https://instagram.com/empresa')


if __name__ == '__main__':
    unittest.main()
