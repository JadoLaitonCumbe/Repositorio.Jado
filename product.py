"""Official product identity and build metadata for GEmpresa-JLC."""

PRODUCT_NAME = "GEmpresa-JLC"
PRODUCT_BRAND = "JLC-tech"
PRODUCT_FULL_NAME = "GEmpresa-JLC — Produto da JLC-tech"
PRODUCT_TAGLINE = "Gestão empresarial inteligente, integrada e preparada para Moçambique."
PRODUCT_VERSION = "1.0.0"
PRODUCT_CODENAME = "Maputo"


def product_payload() -> dict:
    return {
        "name": PRODUCT_NAME,
        "brand": PRODUCT_BRAND,
        "full_name": PRODUCT_FULL_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": PRODUCT_VERSION,
        "codename": PRODUCT_CODENAME,
    }
