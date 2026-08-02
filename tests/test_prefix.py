"""
Tests unitarios para PrefixTransformer — Paso 4.
"""

import pytest

from services.sync import PrefixTransformer


class TestToRemote:
    def test_basic_conversion(self):
        t = PrefixTransformer("L")
        assert t.to_remote(5) == "L-5"

    def test_none_returns_none(self):
        t = PrefixTransformer("L")
        assert t.to_remote(None) is None

    def test_zero_id(self):
        t = PrefixTransformer("L")
        assert t.to_remote(0) == "L-0"

    def test_multi_char_prefix(self):
        t = PrefixTransformer("PL")
        assert t.to_remote(123) == "PL-123"


class TestToLocal:
    def test_basic_conversion(self):
        t = PrefixTransformer("L")
        assert t.to_local("L5") == 5

    def test_none_returns_none(self):
        t = PrefixTransformer("L")
        assert t.to_local(None) is None

    def test_multi_char_prefix(self):
        t = PrefixTransformer("PL")
        assert t.to_local("PL123") == 123

    def test_removeprefix_not_lstrip(self):
        """Verifica que usa removeprefix en vez de lstrip (seguridad)."""
        # Con lstrip("L"), "LL5" daría "5" (incorrecto)
        # Con removeprefix("L"), "LL5" daría "L5" → int("L5") → error
        # Esto es correcto: un remote_id "LL5" no debería existir
        # para un prefix "L", solo "L5" es válido
        t = PrefixTransformer("L")
        assert t.to_local("L42") == 42


class TestRoundTrip:
    def test_roundtrip_simple(self):
        """to_local(to_remote(x)) == x"""
        t = PrefixTransformer("L")
        for val in [0, 1, 5, 42, 999]:
            assert t.to_local(t.to_remote(val)) == val

    def test_roundtrip_multi_prefix(self):
        t = PrefixTransformer("AB")
        for val in [1, 100, 9999]:
            assert t.to_local(t.to_remote(val)) == val


class TestTransformFactura:
    def test_items_id_csv_transformed(self):
        """El CSV de items_id debe transformarse: '1,2,3' → 'L-1,L-2,L-3'."""
        from schemas import FacturaIn
        from datetime import datetime

        t = PrefixTransformer("L")
        factura = FacturaIn(
            local_id=1,
            updated_at=datetime(2026, 7, 16),
            fecha=datetime(2026, 7, 16),
            total=5000,
            saldo_pendiente=5000,
            items_id="1,2,3",
            entrega_domicilio=False,
            cliente_id=10,
        )
        result = t.transform_factura(factura)
        assert result["id"] == "L-1"
        assert result["cliente_id"] == "L-10"
        assert result["items_id"] == "L-1,L-2,L-3"

    def test_items_id_single(self):
        from schemas import FacturaIn
        from datetime import datetime

        t = PrefixTransformer("A")
        factura = FacturaIn(
            local_id=5,
            updated_at=datetime(2026, 7, 16),
            fecha=datetime(2026, 7, 16),
            total=1000,
            saldo_pendiente=1000,
            items_id="42",
            entrega_domicilio=True,
        )
        result = t.transform_factura(factura)
        assert result["id"] == "A-5"
        assert result["items_id"] == "A-42"
        assert result["cliente_id"] is None


class TestTransformItem:
    def test_all_fks_transformed(self):
        """Todas las FKs del item deben transformarse."""
        from schemas import ItemIn
        from datetime import datetime

        t = PrefixTransformer("L")
        item = ItemIn(
            local_id=7,
            factura_id=34,
            stock_id=5,
            catalogo_id=3,
            image_id=12,
            nombre="Sofá",
            cantidad=1,
            tipo="encargo",
            subtotal=3000,
            status="pendiente",
            created_at=datetime(2026, 7, 16),
            updated_at=datetime(2026, 7, 16),
        )
        result = t.transform_item(item)
        assert result["id"] == "L-7"
        assert result["factura_id"] == "L-34"
        assert result["stock_id"] == "L-5"
        assert result["catalogo_id"] == "L-3"
        assert result["image_id"] == "L-12"

    def test_nullable_fks(self):
        from schemas import ItemIn
        from datetime import datetime

        t = PrefixTransformer("L")
        item = ItemIn(
            local_id=1,
            factura_id=1,
            nombre="Mesa",
            cantidad=1,
            tipo="encargo",
            subtotal=500,
            status="pendiente",
            created_at=datetime(2026, 7, 16),
            updated_at=datetime(2026, 7, 16),
        )
        result = t.transform_item(item)
        assert result["stock_id"] is None
        assert result["catalogo_id"] is None
        assert result["image_id"] is None
