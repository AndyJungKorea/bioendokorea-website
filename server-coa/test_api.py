import io
import os
import sys
import tempfile
import unittest
from pathlib import Path


class CoaApiUploadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["COA_DATA_DIR"] = cls.temp_dir.name
        os.environ["COA_ADMIN_TOKEN"] = "test-admin-token"
        os.environ["COA_DOWNLOAD_SECRET"] = "test-download-secret"
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import coa_app

        cls.module = coa_app
        cls.client = coa_app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_upload_is_searchable_by_every_lot(self):
        response = self.client.post(
            "/admin/upload",
            headers={"X-CoA-Admin-Token": "test-admin-token"},
            data={
                "lots": "26030133, 26030134",
                "sourceBatch": "automated-test",
                "file": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "verified-coa.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["document"]["verifiedLots"], ["26030133", "26030134"])

        for lot in response.json["document"]["lots"]:
            lookup = self.client.get(f"/lookup?lot={lot}")
            self.assertEqual(lookup.status_code, 200)
            self.assertTrue(
                any(
                    document["name"] == "verified-coa.pdf"
                    and document["size"] == len(b"%PDF-1.4\n%%EOF\n")
                    for document in lookup.json["documents"]
                )
            )


if __name__ == "__main__":
    unittest.main()
