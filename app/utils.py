import base64
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import qrcode


def make_qr_base64(value):
    image = qrcode.make(value)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return base64.b64encode(output.getvalue()).decode('ascii')


def _crc16(data):
    crc = 0xFFFF
    for character in data.encode('ascii'):
        crc ^= character << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f'{crc:04X}'


def promptpay_payload(promptpay_id, amount):
    recipient = str(promptpay_id).replace('-', '').replace(' ', '')
    if re.fullmatch(r'0[0-9]{9}', recipient):
        merchant = '0016A00000067701011101130066' + recipient[1:]
    elif re.fullmatch(r'[0-9]{13}', recipient):
        merchant = '0016A0000006770101110213' + recipient
    elif re.fullmatch(r'[0-9]{15}', recipient):
        merchant = '0016A0000006770101110315' + recipient
    else:
        raise ValueError('Invalid PromptPay recipient')
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value <= 0 or value > Decimal('99999999.99'):
            raise ValueError('Invalid PromptPay amount')
        if value != value.quantize(Decimal('0.01')):
            raise ValueError('Amount must have at most two decimal places')
    except InvalidOperation:
        raise ValueError('Invalid PromptPay amount') from None
    amount_text = f'{value:.2f}'
    payload = f'00020101021229{len(merchant):02}{merchant}5802TH530376454{len(amount_text):02}{amount_text}6304'
    return payload + _crc16(payload)


def generate_promptpay_qr_base64(promptpay_id, amount):
    return make_qr_base64(promptpay_payload(promptpay_id, amount))


def iso(value):
    if value is None:
        return ''
    return value.isoformat(timespec='seconds') if isinstance(value, datetime) else str(value)
