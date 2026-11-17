"""Local text extraction for teacher material. No model, OCR, file execution or writes."""
import io
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from scenarios.ink_drama.domain import UserError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_MATERIAL_CHARACTERS = 20_000
MAX_PDF_PAGES = 100
MAX_XML_BYTES = 8 * 1024 * 1024
WORD_NAMESPACE = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def clean_text(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(line.rstrip() for line in text.split('\n'))).strip()


def text_file(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        encodings = ('utf-16',)
    else:
        encodings = ('utf-8-sig', 'gb18030')
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            if '\x00' in text:
                break
            return text
        except UnicodeError:
            continue
    raise UserError('TXT编码无法识别，请另存为UTF-8文本后重新上传')


def word_file(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (len(entries) > 2000 or sum(item.file_size for item in entries) > 32 * 1024 * 1024
                    or any(item.file_size > MAX_XML_BYTES for item in entries if item.filename.endswith('.xml'))):
                raise UserError('Word文档解压后过大，请精简图片和内容后重新上传')
            if 'word/document.xml' not in archive.namelist():
                raise UserError('文件不是有效的Word文档，请另存为.docx后上传')
            parts = []
            for name in ('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml'):
                if name not in archive.namelist():
                    continue
                root = ElementTree.fromstring(archive.read(name))
                paragraphs = []
                for paragraph in root.iter(WORD_NAMESPACE + 'p'):
                    pieces = []
                    for node in paragraph.iter():
                        if node.tag == WORD_NAMESPACE + 't': pieces.append(node.text or '')
                        elif node.tag == WORD_NAMESPACE + 'tab': pieces.append('\t')
                        elif node.tag in (WORD_NAMESPACE + 'br', WORD_NAMESPACE + 'cr'): pieces.append('\n')
                    if ''.join(pieces).strip(): paragraphs.append(''.join(pieces))
                if paragraphs:
                    parts.append(('资料来源：文档注释\n' if name != 'word/document.xml' else '') + '\n'.join(paragraphs))
            return '\n\n'.join(parts)
    except UserError:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError, OSError, ValueError) as exc:
        raise UserError('Word文档无法读取，请检查文件是否损坏或加密，另存为.docx后重试') from exc


def pdf_file(data):
    from PyPDF2 import PdfReader
    try:
        if not data.lstrip().startswith(b'%PDF-'):
            raise UserError('文件内容不是PDF，请检查文件格式后重新上传')
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise UserError('暂不支持加密PDF，请先解除密码保护后上传')
        pages = len(reader.pages)
        if pages > MAX_PDF_PAGES:
            raise UserError(f'PDF最多支持{MAX_PDF_PAGES}页，请拆分或精简后重新上传')
        parts, empty_pages, characters = [], 0, 0
        for page in reader.pages:
            text = page.extract_text() or ''
            empty_pages += not text.strip()
            characters += len(text)
            if characters > MAX_MATERIAL_CHARACTERS:
                raise UserError('提取文字超过2万字，请精简或分段上传；未截断资料')
            parts.append(text)
        return '\n\n'.join(parts), pages, empty_pages
    except UserError:
        raise
    except Exception as exc:
        raise UserError('PDF文字提取失败，请检查文件是否损坏，或另存为文字版PDF后重试') from exc


def extract_material(data, filename):
    filename = PurePosixPath((filename or '').replace('\\', '/')).name
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename).strip()
    extension = PurePosixPath(filename).suffix.lower()
    if len(filename)>160:
        filename=filename[:160-len(extension)]+extension
    if extension not in ('.docx', '.pdf', '.txt'):
        raise UserError('请上传Word（.docx）、PDF或TXT文件；旧版.doc请先另存为.docx')
    if not data:
        raise UserError('上传的文件为空，请重新选择资料')
    if len(data) > MAX_FILE_BYTES:
        raise UserError('资料文件不能超过10MB，请精简后重新上传')
    warnings, pages = [], None
    if extension == '.docx':
        text = word_file(data)
    elif extension == '.pdf':
        text, pages, empty_pages = pdf_file(data)
        if empty_pages:
            warnings.append(f'有{empty_pages}页未提取到文字，可能是扫描图片或空白页，请核对预览。')
    else:
        text = text_file(data)
    text = clean_text(text)
    if not text:
        raise UserError('未提取到可用文字。扫描版PDF和图片文字暂不支持识别，请上传文字版文档或粘贴文字。')
    if len(text) > MAX_MATERIAL_CHARACTERS:
        raise UserError('提取文字超过2万字，请精简或分段上传；未截断资料')
    return dict(filename=filename, format=extension[1:], text=text,
                characters=len(text), pages=pages, warnings=warnings,
                max_characters=MAX_MATERIAL_CHARACTERS)
