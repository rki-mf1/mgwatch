import gzip

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.test import override_settings

from mgw_api.models import validate_fasta_content
from mgw_api.models import validate_fasta_extension


class FastaUploadValidationTests(SimpleTestCase):
    def test_rejects_arbitrary_gzip_extension(self):
        upload = SimpleUploadedFile("sample.gz", gzip.compress(b">seq\nACGT\n"))

        with self.assertRaises(ValidationError):
            validate_fasta_extension(upload)

    def test_accepts_fasta_gzip_extension(self):
        upload = SimpleUploadedFile("sample.fasta.gz", gzip.compress(b">seq\nACGT\n"))

        validate_fasta_extension(upload)
        validate_fasta_content(upload)

    def test_rejects_invalid_sequence_line_after_first_record(self):
        upload = SimpleUploadedFile("sample.fa", b">seq1\nACGT\n>seq2\nACGTX\n")

        with self.assertRaises(ValidationError):
            validate_fasta_content(upload)

    @override_settings(MAX_FASTA_UPLOAD_SIZE=10)
    def test_rejects_excessive_decompressed_gzip_content(self):
        upload = SimpleUploadedFile("sample.fa.gz", gzip.compress(b">seq\nACGTACGT\n"))

        with self.assertRaises(ValidationError):
            validate_fasta_content(upload)
