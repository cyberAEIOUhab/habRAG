#!/usr/bin/env python3
"""
Extract metadata from EPUB files by directly reading the ZIP/XML structure.
EPUB = ZIP archive containing META-INF/container.xml → OPF file → metadata.

Usage:
    python bookdata/scripts/extract_epub_metadata.py
"""

import json
import sys
import io
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

EPUB_DIR = r"C:\Users\notch\Desktop\哈布斯堡史"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOKDATA_FILE = os.path.join(BASE_DIR, "bookdata.json")

# XML namespaces used in EPUB OPF files
NS = {
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
}


def find_opf_path(zf):
    """Read META-INF/container.xml to find the OPF file path."""
    try:
        container_xml = zf.read('META-INF/container.xml')
        root = ET.fromstring(container_xml)
        # <container><rootfiles><rootfile full-path="..."/></rootfiles></container>
        for rootfile in root.iter():
            if 'full-path' in rootfile.attrib:
                return rootfile.attrib['full-path']
    except Exception:
        pass
    # Fallback: try common names
    for name in ['content.opf', 'OEBPS/content.opf', 'OPS/content.opf']:
        if name in zf.namelist():
            return name
    return None


def parse_opf(zf, opf_path):
    """Parse the OPF XML to extract metadata."""
    try:
        opf_xml = zf.read(opf_path)
        # Register namespaces for cleaner parsing
        for prefix, uri in NS.items():
            ET.register_namespace(prefix, uri)
        root = ET.fromstring(opf_xml)
    except Exception as e:
        return {'error': f'Failed to parse OPF: {e}'}

    metadata = {}
    meta = root.find('.//opf:metadata', NS) or root.find('.//{http://www.idpf.org/2007/opf}metadata')

    if meta is None:
        # Try without namespace
        meta = root.find('.//metadata')
    if meta is None:
        return {'error': 'No metadata element found in OPF'}

    # Helper: get text of first matching element
    def get_dc(tag):
        """Try with namespace, then bare tag."""
        for ns_prefix in ['dc:', '{http://purl.org/dc/elements/1.1/}']:
            el = meta.find(f'{ns_prefix}{tag}')
            if el is not None and el.text:
                return el.text.strip()
        # Try bare tag
        el = meta.find(tag)
        if el is not None and el.text:
            return el.text.strip()
        return None

    def get_all(tag):
        """Get all matching elements' text."""
        results = []
        for ns_prefix in ['dc:', '{http://purl.org/dc/elements/1.1/}']:
            for el in meta.findall(f'{ns_prefix}{tag}'):
                if el is not None and el.text:
                    results.append(el.text.strip())
        if not results:
            for el in meta.findall(tag):
                if el is not None and el.text:
                    results.append(el.text.strip())
        return results

    metadata['title'] = get_dc('title')
    metadata['creator'] = get_dc('creator')
    metadata['contributor'] = get_all('contributor')
    metadata['publisher'] = get_dc('publisher')
    metadata['date'] = get_dc('date')
    metadata['language'] = get_dc('language')
    metadata['identifier'] = get_all('identifier')
    metadata['subject'] = get_all('subject')
    metadata['description'] = get_dc('description')
    metadata['rights'] = get_dc('rights')
    metadata['source'] = get_dc('source')
    metadata['type'] = get_dc('type')

    # Try dcterms:modified, dcterms:issued
    # (using the namespace URIs already in NS dict)
    # Actually let's also try meta elements with name/content
    for meta_el in meta.findall('{http://www.idpf.org/2007/opf}meta'):
        name = meta_el.get('name')
        content = meta_el.get('content')
        if name and content:
            metadata[f'meta_{name}'] = content

    return metadata


def count_spine_items(zf, opf_path):
    """Count spine items to approximate page count."""
    try:
        opf_xml = zf.read(opf_path)
        root = ET.fromstring(opf_xml)
        spine = root.find('.//opf:spine', NS) or root.find('.//{http://www.idpf.org/2007/opf}spine')
        if spine is None:
            spine = root.find('.//spine')
        if spine is not None:
            items = spine.findall('{http://www.idpf.org/2007/opf}itemref') or spine.findall('itemref')
            return len(items)
    except Exception:
        pass
    return None


def extract_epub(filepath):
    """Extract all metadata from an EPUB file."""
    result = {
        'filename': os.path.basename(filepath),
        'filepath': filepath,
        'file_size_mb': round(os.path.getsize(filepath) / (1024 * 1024), 2),
    }

    try:
        with zipfile.ZipFile(filepath, 'r') as zf:
            # List all files
            all_files = zf.namelist()
            result['internal_file_count'] = len(all_files)

            # Find OPF
            opf_path = find_opf_path(zf)
            result['opf_path'] = opf_path

            if opf_path:
                metadata = parse_opf(zf, opf_path)
                result['metadata'] = metadata
                spine_count = count_spine_items(zf, opf_path)
                result['spine_items'] = spine_count
            else:
                result['error'] = 'Could not find OPF file'
                result['file_list_preview'] = all_files[:30]

    except zipfile.BadZipFile:
        result['error'] = 'Not a valid ZIP/EPUB file'
    except Exception as e:
        result['error'] = str(e)

    return result


def main():
    # Find all EPUB files
    epub_files = []
    for f in os.listdir(EPUB_DIR):
        if f.lower().endswith('.epub'):
            epub_files.append(os.path.join(EPUB_DIR, f))

    print(f'Found {len(epub_files)} EPUB files\n')
    print('=' * 80)

    results = []
    for i, fp in enumerate(sorted(epub_files)):
        print(f'\n[{i+1}/{len(epub_files)}] {os.path.basename(fp)[:90]}...')
        info = extract_epub(fp)
        results.append(info)

        print(f'  Size: {info["file_size_mb"]} MB')
        print(f'  Internal files: {info.get("internal_file_count", "N/A")}')
        print(f'  OPF path: {info.get("opf_path", "N/A")}')
        print(f'  Spine items: {info.get("spine_items", "N/A")}')

        meta = info.get('metadata', {})
        if 'error' in meta:
            print(f'  METADATA ERROR: {meta["error"]}')
        else:
            print(f'  Title:       {meta.get("title", "N/A")}')
            print(f'  Creator:     {meta.get("creator", "N/A")}')
            print(f'  Publisher:   {meta.get("publisher", "N/A")}')
            print(f'  Date:        {meta.get("date", "N/A")}')
            print(f'  Language:    {meta.get("language", "N/A")}')
            print(f'  Identifier:  {meta.get("identifier", [])}')
            print(f'  Description: {(meta.get("description") or "")[:120]}')
            if meta.get('contributor'):
                print(f'  Contributors: {meta["contributor"]}')
            if meta.get('subject'):
                print(f'  Subjects:     {meta["subject"][:5]}')
            # dcterms / meta fields
            extra_meta = {k: v for k, v in meta.items() if k.startswith('meta_')}
            if extra_meta:
                print(f'  Extra meta:   {extra_meta}')

    # Save results
    output_path = os.path.join(BASE_DIR, "bookdata", "epub_metadata_extract.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'\n\nResults saved to: {output_path}')
    print(f'Total EPUBs processed: {len(results)}')


if __name__ == '__main__':
    main()
