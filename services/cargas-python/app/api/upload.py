"""Multipart acotado, exclusivamente en memoria; nunca usa archivos temporales."""
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header


class InputError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


async def receive_file(request, limit):
    content_type, options = parse_options_header(request.headers.get('content-type', ''))
    boundary = options.get(b'boundary')
    if content_type != b'multipart/form-data' or not boundary or len(boundary) > 70:
        raise InputError('MULTIPART_INVALIDO')
    content, headers = bytearray(), {}
    header_name, header_value = bytearray(), bytearray()
    parts, ended, filename = 0, False, None

    def begin():
        nonlocal parts
        parts += 1
        if parts != 1:
            raise InputError('UN_ARCHIVO_REQUERIDO')

    def field(data, start, end):
        header_name.extend(data[start:end])

    def value(data, start, end):
        header_value.extend(data[start:end])

    def header_end():
        key = bytes(header_name).lower()
        if key in headers:
            raise InputError('MULTIPART_INVALIDO')
        headers[key] = bytes(header_value)
        header_name.clear()
        header_value.clear()

    def headers_end():
        nonlocal filename
        disposition, opts = parse_options_header(headers.get(b'content-disposition', b''))
        if disposition != b'form-data' or opts.get(b'name') != b'archivo' or b'filename' not in opts:
            raise InputError('UN_ARCHIVO_REQUERIDO')
        try:
            filename = opts[b'filename'].decode('utf-8')
        except UnicodeError as exc:
            raise InputError('NOMBRE_INVALIDO') from exc
        if not filename or len(filename) > 200 or any(ord(c) < 32 for c in filename) or '/' in filename or '\\' in filename:
            raise InputError('NOMBRE_INVALIDO')
        if not filename.lower().endswith('.xlsx'):
            raise InputError('EXTENSION_INVALIDA')

    def data(chunk, start, end):
        if len(content) + end - start > limit:
            raise InputError('ARCHIVO_DEMASIADO_GRANDE', 413)
        content.extend(chunk[start:end])

    def finish():
        nonlocal ended
        ended = True

    parser = MultipartParser(boundary, dict(on_part_begin=begin, on_header_field=field,
        on_header_value=value, on_header_end=header_end, on_headers_finished=headers_end,
        on_part_data=data, on_end=finish))
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit + 16384:
                raise InputError('ARCHIVO_DEMASIADO_GRANDE', 413)
            parser.write(chunk)
        parser.finalize()
    except InputError:
        raise
    except Exception as exc:
        raise InputError('MULTIPART_INVALIDO') from exc
    if not ended or parts != 1 or filename is None:
        raise InputError('UN_ARCHIVO_REQUERIDO')
    if not content:
        raise InputError('ARCHIVO_VACIO')
    return filename, bytes(content)
