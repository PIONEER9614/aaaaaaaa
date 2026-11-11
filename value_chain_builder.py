"""
밸류체인 테마 추출 빌더 (Value Chain Theme Extractor)
- 네이버페이 증권 테마 API (총 265개 테마) 기반 1차 밸류체인 구조화
- 동적 페이지네이션: totalCount에 따라 100건 초과 테마(예: 143개사 등)도 누락 없이 전 페이지 순회
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

def fetch_theme_with_pagination(theme_no, page_size=100):
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
            time.sleep(1.0) # 다중 페이지 요청 간 1.0초 지연
    
    return all_stocks, item_map, theme_desc, total_count

def build_all(output_dir='data/value_chain'):
    os.makedirs(output_dir, exist_ok=True)
    overview = {}
    total_resolved = 0
    total_missing = 0
    
    print('=== Starting Dynamic Paginated Value Chain Extraction (Delay: >=1.0s) ===')
    for sector_key, themes in SECTORS.items():
        sector_data = {'sector': sector_key, 'stages': []}
        total_companies = set()
        print(f'Fetching sector: {sector_key}...')
        for no, theme_name, stage_name in themes:
            try:
                all_stocks, item_map, theme_desc, total_count = fetch_theme_with_pagination(no, page_size=100)
                comp_list = []
                for code, info in item_map.items():
                    name = all_stocks.get(code)
                    if not name:
                        total_missing += 1
                        name = code
                    else:
                        total_resolved += 1
                    comp_list.append({'code': code, 'name': name, 'role': info})
                    total_companies.add(code)
                
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
            time.sleep(1.0) # 테마 간 요청 1.0초 지연

        fpath = os.path.join(output_dir, f'{sector_key}_value_chain.json')
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(sector_data, f, ensure_ascii=False, indent=2)
        overview[sector_key] = {
            'total_stages': len(sector_data['stages']),
            'total_unique_companies': len(total_companies),
            'file': fpath
        }
        print(f'  ✓ Saved: {sector_key} ({len(total_companies)} companies)')

    summary_path = os.path.join(output_dir, 'mega_sectors_overview.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)
    print(f'\nAll Value Chains Successfully Built! (Resolved: {total_resolved}, Missing: {total_missing})')

if __name__ == '__main__':
    build_all()
