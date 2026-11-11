"""
밸류체인 마스터 빌더 (Value Chain Master Builder)
- 네이버페이 증권 테마 API, KRX/WICS 및 DART 사업보고서 연계
- 국내 증시 핵심 섹터별 가치사슬(Upstream -> Midstream -> Downstream -> Aftermarket) 자동 구조화
"""

import os
import json
import time
import urllib.request

SECTORS = {
    '반도체_AI': [
        (14, '웨이퍼/재료/소재', '1_Upstream_소재부품'),
        (12, '반도체 장비', '2_Midstream_제조장비'),
        (608, '반도체 기판(FC-BGA/PCB/MLB)', '2_Midstream_패키징기판'),
        (287, 'PCB(FPCB 등)', '2_Midstream_기판회로'),
        (536, 'HBM(고대역폭메모리)', '3_Downstream_고성능메모리'),
        (547, 'CXL(컴퓨트익스프레스링크)', '3_Downstream_차세대인터페이스'),
        (307, '시스템반도체/팹리스/디자인하우스', '3_Downstream_칩설계'),
        (155, '반도체 대표주(IDM/파운드리)', '4_Aftermarket_완제품생산')
    ],
    '전력망_원전': [
        (178, '전선/케이블', '1_Upstream_기초소재전선'),
        (520, '피팅/밸브(배관자재)', '1_Upstream_배관기초부품'),
        (123, '전력설비/초고압변압기', '2_Midstream_중전기기완제품'),
        (229, '스마트그리드/배전망', '3_Downstream_배전전력망'),
        (329, '전력저장장치(ESS)', '3_Downstream_에너지저장'),
        (205, '원자력발전/SMR', '4_Aftermarket_발전원인프라')
    ],
    '조선_해양': [
        (520, '피팅/밸브(배관자재)', '1_Upstream_배관기초부품'),
        (94, '조선기자재/엔진/보냉재', '2_Midstream_기자재모듈'),
        (30, '조선(건조/조선사)', '3_Downstream_완제품선박'),
        (36, '해운(선주사/운송)', '4_Aftermarket_선주사운항')
    ],
    'K뷰티_미용의료': [
        (110, '화장품(원료/용기/ODM/브랜드)', '1_2_3_원료_제조_브랜드'),
        (513, '미용기기(RF/HIFU)', '3_Downstream_에스테틱기기'),
        (397, '보톡스/필러', '3_Downstream_메디컬에스테틱')
    ],
    '2차전지_배터리': [
        (523, '리튬/원자재광물', '1_Upstream_원자재광물'),
        (446, '소재/부품(양/음극재,전해액,분리막)', '2_Midstream_핵심소재'),
        (445, '2차전지 장비', '2_Midstream_제조공정장비'),
        (449, '배터리 셀 제조(생산)', '3_Downstream_완성셀제조'),
        (500, '폐배터리 리사이클링', '4_Aftermarket_재활용')
    ],
    '방위산업_우주항공': [
        (379, '항공기부품/특수소재', '1_Upstream_부품소재'),
        (144, '방위산업(유도/기동/화력)', '2_Midstream_체계종합'),
        (200, '우주항공(누리호/위성)', '3_Downstream_발사체위성')
    ],
    '바이오_제약': [
        (172, '제약업체(전통제약)', '1_2_전통제약_원료'),
        (241, '바이오시밀러(복제약/CDMO)', '2_Midstream_바이오의약품'),
        (389, '면역항암제(신약개발)', '3_Downstream_바이오텍R&D'),
        (540, '비만치료제(GLP-1 등)', '3_Downstream_차세대치료제')
    ]
}

def build_all(output_dir='data/value_chain'):
    os.makedirs(output_dir, exist_ok=True)
    overview = {}
    
    print('=== Starting Value Chain Extraction ===')
    for sector_key, themes in SECTORS.items():
        sector_data = {'sector': sector_key, 'stages': []}
        total_companies = set()
        print(f'Fetching sector: {sector_key}...')
        for no, theme_name, stage_name in themes:
            url = f'https://m.stock.naver.com/api/stocks/theme/{no}'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as resp:
                    d = json.loads(resp.read().decode('utf-8'))
                    stocks = {s['itemCode']: s['stockName'] for s in d.get('stocks', [])}
                    item_map = d.get('themeItemInfoMap', {})
                    comp_list = []
                    for code, info in item_map.items():
                        name = stocks.get(code, code)
                        comp_list.append({'code': code, 'name': name, 'role': info})
                        total_companies.add(code)
                    sector_data['stages'].append({
                        'stage': stage_name,
                        'theme_no': no,
                        'theme_name': theme_name,
                        'description': d.get('themeDescription', ''),
                        'company_count': len(comp_list),
                        'companies': comp_list
                    })
            except Exception as e:
                print(f'  Error theme {no}: {e}')
            time.sleep(0.1)

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
    print('\nAll Value Chains Successfully Built!')

if __name__ == '__main__':
    build_all()
