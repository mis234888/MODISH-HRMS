"""Generate chat keys into a NEW private file, without printing secret values.

Usage: python tools/chat_keys.py --output .env.chat --subject mailto:admin@example.com
Copy the resulting settings into your private deployment environment. Never
replace a working CHAT_ENCRYPTION_KEY: doing so makes old messages unreadable.
"""
import argparse
import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def generate(subject):
    if not subject.startswith(("mailto:", "https://")) or any(c.isspace() for c in subject):
        raise ValueError("Use a mailto: address or HTTPS contact URL without whitespace.")
    private = ec.generate_private_key(ec.SECP256R1())
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return {
        "CHAT_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "CHAT_VAPID_PUBLIC_KEY": encode(private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
        "CHAT_VAPID_PRIVATE_KEY": encode(private.private_numbers().private_value.to_bytes(32, "big")),
        "CHAT_VAPID_SUBJECT": subject,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New private file; existing files are never overwritten")
    parser.add_argument("--subject", required=True, help="Contact URI for the push provider, e.g. mailto:admin@example.com")
    args = parser.parse_args()
    if not args.output.parent.is_dir():
        parser.error("Output parent directory must already exist.")
    try:
        settings = generate(args.subject)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write("# Private chat settings. Back up securely; never commit.\n")
            for name, value in settings.items():
                output.write(f"{name}={value}\n")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Created private settings file: {args.output}. No keys were printed.")
    if os.name == "nt":
        print("On Windows, restrict the file's Security permissions to the application owner.")


if __name__ == "__main__":
    main()
