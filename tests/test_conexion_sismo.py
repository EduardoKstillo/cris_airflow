import sys
sys.path.insert(0, '/app/airflow')

from plugins.extractors.sismo_extractor import SISMOExtractor


def test_connection():
    extractor = SISMOExtractor()

    try:
        if extractor.connect():
            print("✅ CONEXIÓN A SISMO EXITOSA")
            return True

        print("❌ NO SE PUDO CONECTAR A SISMO")
        return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

    finally:
        extractor.close()


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)