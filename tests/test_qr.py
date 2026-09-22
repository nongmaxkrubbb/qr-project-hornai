import base64
import io
import unittest
from decimal import Decimal
from PIL import Image
from app.utils import _crc16, promptpay_payload, generate_promptpay_qr_base64


def tlv(payload):
    values = {}
    while payload:
        key, length = payload[:2], int(payload[2:4])
        values[key], payload = payload[4:4+length], payload[4+length:]
    return values


class PromptPayTests(unittest.TestCase):
    def test_crc_standard_check_vector(self):
        self.assertEqual(_crc16('123456789'), '29B1')

    def test_phone_amount_and_crc_are_embedded_exactly(self):
        payload = promptpay_payload('081-234-5678', Decimal('45.50'))
        fields = tlv(payload)
        self.assertEqual(fields['53'], '764')
        self.assertEqual(fields['58'], 'TH')
        self.assertEqual(fields['54'], '45.50')
        self.assertEqual(tlv(fields['29'])['01'], '0066812345678')
        self.assertEqual(fields['63'], _crc16(payload[:-4]))

    def test_national_id_and_wallet_use_distinct_fields(self):
        self.assertEqual(tlv(tlv(promptpay_payload('1234567890123', 10))['29'])['02'], '1234567890123')
        self.assertEqual(tlv(tlv(promptpay_payload('123456789012345', 10))['29'])['03'], '123456789012345')

    def test_invalid_recipients_and_amounts_never_generate_payment_qr(self):
        for recipient in ('', 'invalid', '1234567890', '๐๘๑๒๓๔๕๖๗๘'):
            with self.subTest(recipient=recipient), self.assertRaises(ValueError):
                promptpay_payload(recipient, 10)
        for amount in ('NaN', 'Infinity', '-1', '0', '1.001', '100000000'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                promptpay_payload('0812345678', amount)

    def test_qr_is_a_decodable_png_container(self):
        raw = base64.b64decode(generate_promptpay_qr_base64('0812345678', 45))
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertGreater(image.width, 100)
