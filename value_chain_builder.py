"""
밸류체인 테마 추출 빌더 (Value Chain Theme Extractor)
- 네이버페이 증권 테마 API (총 265개 테마) 기반 1차 밸류체인 구조화
- 동적 페이지네이션: totalCount에 따라 100건 초과 테마도 전 페이지 순회
- 페이징 드롭 대비 2차 안전망: 쪽 간 종목 겹침/누락 시 https://m.stock.naver.com/api/stock/{code}/basic 단건 조회로 보완
- DART 사업보고서 교차 검증은 추후 과제
- 크롤링 규칙: 요청 간격 최소 1.0초 준수
"""

import os
import json
import time
import math
import urllib.request

SECTORS = {
    '반도체_AI': [
        (14, '웨이퍼/재료/소재', '1_소재부품'),
        (12, '반도체 장비', '2_장비'),
        (608, '반도체 기판(FC-BGA/PCB/MLB)', '2_기판부품'),
        (287, 'PCB(FPCB 등)', '2_기판회로'),
        (536, 'HBM(고대역폭메모리)', '3_고성능메모리'),
        (547, 'CXL(컴퓨트익스프레스링크)', '3_차세대인터페이스'),
        (307, '시스템반도체/팹리스/디자인하우스', '3_칩설계'),
        (155, '반도체 대표주(IDM/파운드리)', '4_완제품제조_IDM')
    ],
    '전력망_원전': [
        (178, '전선/케이블', '1_기초소재_전선'),
        (520, '피팅/밸브(배관자재)', '1_배관기초부품'),
        (123, '전력설비/초고압변압기', '2_중전기기완제품'),
        (229, '스마트그리드/배전망', '3_배전전력망'),
        (329, '전력저장장치(ESS)', '3_에너지저장'),
        (205, '원자력발전/SMR', '4_발전원인프라')
    ],
    '조선_해양': [
        (520, '피팅/밸브(배관자재)', '1_배관기초부품'),
        (94, '조선기자재/엔진/보냉재', '2_기자재모듈'),
        (30, '조선(건조/조선사)', '3_완제품선박'),
        (36, '해운(선주사/운송)', '4_선주사운항_MRO')
    ],
    'K뷰티_미용의료': [
        (110, '화장품(원료/용기/ODM/브랜드)', '1_2_3_원료_제조_브랜드'),
        (513, '미용기기(RF/HIFU)', '3_에스테틱기기'),
        (397, '보톡스/필러', '3_메디컬에스테틱')
    ],
    '2차전지_배터리': [
        (523, '리튬/원자재광물', '1_원자재광물'),
        (446, '소재/부품(양/음극재,전해액,분리막)', '2_핵심소재'),
        (445, '2차전지 장비', '2_제조공정장비'),
        (449, '배터리 셀 제조(생산)', '3_완성셀제조'),
        (500, '폐배터리 리사이클링', '4_재활용_리사이클링')
    ],
    '방위산업_우주항공': [
        (379, '항공기부품/특수소재', '1_부품소재'),
        (144, '방위산업(유도/기동/화력)', '2_체계종합'),
        (200, '우주항공(누리호/위성)', '3_발사체위성')
    ],
    '바이오_제약': [
        (172, '제약업체(전통제약)', '1_2_전통제약_원료'),
        (241, '바이오시밀러(복제약/CDMO)', '2_바이오의약품'),
        (389, '면역항암제(신약개발)', '3_바이오텍R&D'),
        (540, '비만치료제(GLP-1 등)', '3_차세대치료제')
    ]
}

def resolve_single_stock_name(code):
    """페이징 누락 종목 대상 개별 기본정보 API 단건 조회 (우 사부 검수 1안)"""
    url = f'https://m.stock.naver.com/api/stock/{code}/basic'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            return d.get('stockName')
    except Exception as e:
        return None

def fetch_theme(theme_no, page_size=100):
    page = 1
    all_stocks = {}
    item_map = {}
    theme_desc = ''
    total_count = 0

    while True:
        url = f'https://m.stock.naver.com/api/stocks/theme/{theme_no}?page={page}&pageSize={page_size}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            if not theme_desc:
                theme_desc = d.get('themeDescription', '')
            if not item_map:
                item_map = d.get('themeItemInfoMap', {})
            total_count = d.get('totalCount', 0)
            
            for s in d.get('stocks', []):
                all_stocks[s['itemCode']] = s['stockName']
            
            total_pages = math.ceil(total_count / page_size) if total_count else 1
            if page >= total_pages:
                break
            page += 1
            time.sleep(1.0) # 다중 페이지 요청 간격 1초

    # 2단계: 페이징 간 종목 겹침/누락으로 빠진 코드 단건 API 안전망 보완
    fallback_filled = 0
    unresolved = 0
    for code in item_map:
        if code not in all_stocks:
            time.sleep(1.0)
            name = resolve_single_stock_name(code)
            if name:
                all_stocks[code] = name
                fallback_filled += 1
            else:
                unresolved += 1

    return all_stocks, item_map, theme_desc, total_count, fallback_filled, unresolved

def build_all(output_dir='data/value_chain', docs_dir='docs'):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)
    overview = {}
    
    total_themes_count = sum(len(v) for v in SECTORS.values())
    themes_over_100 = 0
    total_fallback_filled = 0
    total_unresolved = 0
    total_companies_mapped = 0

    print(f'=== Starting Robust Value Chain Extraction (Total: {total_themes_count} themes) ===')
    for sector_key, themes in SECTORS.items():
        sector_data = {'sector': sector_key, 'stages': []}
        total_companies = set()
        print(f'Fetching sector: {sector_key}...')
        for no, theme_name, stage_name in themes:
            try:
                all_stocks, item_map, theme_desc, total_count, fb_cnt, unres_cnt = fetch_theme(no, page_size=100)
                if total_count > 100:
                    themes_over_100 += 1
                total_fallback_filled += fb_cnt
                total_unresolved += unres_cnt

                comp_list = []
                for code, info in item_map.items():
                    name = all_stocks.get(code, code)
                    comp_list.append({'code': code, 'name': name, 'role': info})
                    total_companies.add(code)
                    total_companies_mapped += 1

                sector_data['stages'].append({
                    'stage': stage_name,
                    'theme_no': no,
                    'theme_name': theme_name,
                    'total_count': total_count,
                    'description': theme_desc,
                    'company_count': len(comp_list),
                    'companies': comp_list
                })
            except Exception as e:
                print(f'  Error theme {no}: {e}')
            time.sleep(1.0) # 테마 간 요청 1초

        fpath = os.path.join(output_dir, f'{sector_key}_value_chain.json')
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(sector_data, f, ensure_ascii=False, indent=2)
        overview[sector_key] = {
            'total_stages': len(sector_data['stages']),
            'total_unique_companies': len(total_companies),
            'file': fpath
        }

    summary_path = os.path.join(output_dir, 'mega_sectors_overview.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)

    # 총람 마크다운 문서 생성
    generate_markdown_summary(output_dir, docs_dir)

    print('\n=== Extraction Summary ===')
    print(f'- 빌더의 33개 테마 중 100곳 넘는 테마 수: {themes_over_100}')
    print(f'- 쪽 겹침/누락으로 빠졌다가 basic API로 채운 코드 수: {total_fallback_filled}')
    print(f'- 끝내 못 채운 코드 수: {total_unresolved}')
    print(f'- 총 매핑된 기업 수: {total_companies_mapped}')

def generate_markdown_summary(input_dir, output_dir):
    import glob
    os.makedirs(output_dir, exist_ok=True)
    files = glob.glob(os.path.join(input_dir, '*_value_chain.json'))
    md = []
    md.append('# 🌐 국내 증시 7대 핵심 섹터 테마 밸류체인 1차 추출 총람\n')
    n_themes = len({t[0] for v in SECTORS.values() for t in v})
    md.append(f'> **데이터 출처:** 네이버페이 증권 테마 API (총 265개 테마 중 {n_themes}개 핵심 테마 추출)')
    md.append('> **데이터 정합성 및 한계 공지:**')
    md.append('> 1. 본 문서는 네이버 증권 테마 API에서 제공하는 종목별 종목 설명(`themeItemInfoMap`)을 1차 수집·정리한 자료입니다.')
    md.append('> 2. **DART 사업보고서 교차 검증은 추후 과제:** 테마 분류 특성상 다각화 기업이나 이전 사업(예: LCD 장비사 등)이 포함될 수 있으며, 실제 매출 비중 및 고객사 납품 관계는 향후 DART 사업의 내용 분석을 통해 2차 정밀 검증해야 합니다.')
    md.append('> 3. 단계 구분(소재/장비/설계/완제품 등)은 각 테마의 산업적 성격을 기준으로 1차 매핑한 결과입니다.\n')

    for fpath in sorted(files):
        with open(fpath, 'r', encoding='utf-8') as f:
            d = json.load(f)
        sector_name = d.get('sector', os.path.basename(fpath).replace('_value_chain.json', ''))
        md.append(f'---\n## 📌 {sector_name}\n')
        for stage in d.get('stages', []):
            stage_title = stage.get('stage')
            theme_title = stage.get('theme_name')
            cnt = stage.get('company_count')
            md.append(f"### [{stage_title}] {theme_title} ({cnt}개사)")
            desc = stage.get('description', '')
            if desc:
                md.append(f"> {desc[:140]}...\n")
            for c in stage.get('companies', [])[:5]:
                role = c.get('role', '')[:100].replace('\n', ' ')
                c_name = c.get('name')
                c_code = c.get('code')
                md.append(f"- **{c_name} ({c_code})**: {role}...")
            if stage.get('company_count', 0) > 5:
                md.append(f"  *(외 {stage.get('company_count') - 5}개 기업 수록)*\n")
            else:
                md.append('')

    doc_path = os.path.join(output_dir, '전_섹터_기업_가치사슬_총람.md')
    with open(doc_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    print(f'Wrote markdown summary to {doc_path} successfully!')

if __name__ == '__main__':
    import sys
    if '--doc-only' in sys.argv:
        # 이미 받아 둔 json으로 총람 문서만 다시 만들기 (네트워크 요청 없음)
        generate_markdown_summary('data/value_chain', 'docs')
    else:
        build_all()
