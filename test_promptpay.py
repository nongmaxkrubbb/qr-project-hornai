def crc16(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
    return f"{crc & 0xFFFF:04X}"

def generate_promptpay_payload(promptpay_id: str, amount: float = 0) -> str:
    # 00: payload format indicator (01)
    # 01: point of initiation method (11 for static, 12 for dynamic)
    payload = "000201010212"
    
    # 29: merchant account information (PromptPay)
    # AID: A000000677010111
    # 01: mobile (00 66 + 9 digits) or 02: national id (13 digits)
    promptpay_id = promptpay_id.replace("-", "").replace(" ", "")
    if len(promptpay_id) == 10 and promptpay_id.startswith("0"):
        # Mobile
        formatted_id = "0066" + promptpay_id[1:]
        merchant_info = f"0016A0000006770101110113{formatted_id}"
    elif len(promptpay_id) == 13:
        # National ID
        merchant_info = f"0016A0000006770101110213{promptpay_id}"
    else:
        # e-Wallet or other
        merchant_info = f"0016A0000006770101110315{promptpay_id}"
        
    payload += f"29{len(merchant_info):02}{merchant_info}"
    payload += "5802TH5303764" # Country code TH, Currency THB
    
    if amount > 0:
        amount_str = f"{amount:.2f}"
        payload += f"54{len(amount_str):02}{amount_str}"
        
    payload += "6304" # CRC tag
    return payload + crc16(payload)

print(generate_promptpay_payload("0812345678", 150.0))
import promptpay
print(promptpay.qrcode.generate_payload("0812345678", 150.0))
