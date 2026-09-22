"""Generate local VAPID values; write them to your deployment secret store."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def main():
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print('VAPID_PUBLIC_KEY=' + encoded(public))
    print('VAPID_PRIVATE_KEY=' + encoded(private.private_numbers().private_value.to_bytes(32, 'big')))
    print('# Keep the private key secret. Configure VAPID_SUBJECT with your operator contact.')


if __name__ == '__main__':
    main()
