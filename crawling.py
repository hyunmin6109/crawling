import asyncio
import json
import time
import glob
import os
from playwright.async_api import async_playwright

MAX_COUNT = 1000

CATEGORY_LIST = [
    {"id": "18254183", "name": "여성_레인부츠"},
    {"id": "18255502", "name": "여성_메리제인슈즈"}
]

async def scrape_category(category_id, category_name):
    results = []
    seen_links = set()
    base_filename = f"danawa_{category_name}_results"

    for file in sorted(glob.glob(f"{base_filename}_*.json")):
        with open(file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                for item in data:
                    seen_links.add(item["링크"])
            except Exception as e:
                print(f"❗ 파일 로딩 실패: {file} → {e}")

    print(f"🔁 {category_name} 기존 수집된 상품 수: {len(seen_links)}개")
    file_index = len(seen_links) // 100

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        detail_page = await browser.new_page()

        category_url = f"https://prod.danawa.com/list/?cate={category_id}"
        await page.goto(category_url)
        await page.wait_for_timeout(3000)

        try:
            await page.click('a.tab_link.tab_compare')
            await page.wait_for_timeout(2000)
            print("✅ 가격비교 탭 클릭 성공")
        except Exception as e:
            print(f"❗ 가격비교 탭 클릭 실패: {e}")

        try:
            await page.click('a.type_list[title*="리스트형"]')
            await page.wait_for_timeout(1500)
            print("✅ 리스트형 탭 클릭 성공")
        except Exception as e:
            print(f"❗ 리스트형 탭 클릭 실패: {e}")

        page_set = 0
        while True:
            page_set += 1
            print(f"\n📦 [{category_name}] {page_set}번째 페이지 세트 탐색 중...")

            for i in range(1, 11):
                try:
                    page_selector = f'div.number_wrap a.num:has-text("{i}")'
                    if await page.query_selector(page_selector):
                        await page.click(page_selector)
                        await page.wait_for_timeout(2500)

                        items = await page.query_selector_all("div.main_prodlist > ul > li.prod_item")
                        product_list = []

                        for item in items:
                            title_el = await item.query_selector("p.prod_name a")
                            price_el = await item.query_selector("p.price_sect strong")
                            if title_el and price_el:
                                title = await title_el.inner_text()
                                link = await title_el.get_attribute("href")
                                price = await price_el.inner_text()

                                if link and link not in seen_links:
                                    seen_links.add(link)
                                    product_list.append({
                                        "title": title.strip(),
                                        "link": link,
                                        "price": price.strip()
                                    })

                        print(f"🔍 수집된 상품 수: {len(product_list)}개")

                        for product in product_list:
                            try:
                                if len(seen_links) >= MAX_COUNT:
                                    print(f"🛑 최대 수집 개수({MAX_COUNT}) 도달 → {category_name} 종료")
                                    await browser.close()
                                    return

                                print(f"👉 상세 페이지 이동 시도: {product['link']}")
                                response = await detail_page.goto(product["link"])
                                if not response or response.status != 200:
                                    print(f"❗ 상세페이지 접근 실패 (응답 없음 또는 비정상): {product['link']}")
                                    continue

                                await detail_page.wait_for_timeout(2000)

                                description = "상세설명 없음"
                                product_category = "알 수 없음"
                                try:
                                    await detail_page.wait_for_selector("div.spec_list > div.items", timeout=3000)
                                    desc_el = await detail_page.query_selector("div.spec_list > div.items")
                                    if desc_el:
                                        description = await desc_el.inner_text()
                                        print(f"📝 상세 설명 수집 성공: {description[:60]}...")
                                        if "/" in description:
                                            product_category = description.split("/")[0].strip()
                                    else:
                                        print("❗ desc_el이 None임")
                                except Exception as e:
                                    print(f"❗ 상세설명 추출 실패: {e}")

                                try:
                                    await detail_page.click("a#danawa-prodBlog-companyReview-button-tab-companyReview")
                                    await detail_page.wait_for_timeout(1500)
                                except:
                                    pass

                                review_list = []
                                try:
                                    current_page = 1
                                    while current_page <= 3:
                                        await detail_page.wait_for_timeout(1000)
                                        review_elements = await detail_page.query_selector_all("div.atc")
                                        for el in review_elements:
                                            text = await el.inner_text()
                                            if text.strip():
                                                review_list.append(text.strip())
                                                if len(review_list) >= 20:
                                                    break
                                        if len(review_list) >= 20:
                                            break
                                        next_selector = f'a.page_num[data-pagenumber="{current_page + 1}"]'
                                        next_btn = await detail_page.query_selector(next_selector)
                                        if next_btn:
                                            await next_btn.click()
                                            current_page += 1
                                            await detail_page.wait_for_selector("div.atc")
                                        else:
                                            break
                                except Exception as e:
                                    print(f"❗ 리뷰 페이징 오류: {e}")

                                result = {
                                    "제품카테고리": product_category,
                                    "제품명": product["title"],
                                    "링크": product["link"],
                                    "가격": product["price"],
                                    "상세설명": description[:1000],
                                    "리뷰": review_list if review_list else ["리뷰 없음"]
                                }

                                results.append(result)
                                print(f"✅ 저장 완료 ({len(seen_links)}개 누적): {product['title']}")

                                if len(results) >= 100:
                                    file_index += 1
                                    filename = f"{base_filename}_{file_index}.json"
                                    with open(filename, "w", encoding="utf-8") as f:
                                        json.dump(results, f, ensure_ascii=False, indent=4)
                                    print(f"💾 중간 저장 완료 → {filename}")
                                    results = []

                                time.sleep(1)

                            except Exception as e:
                                print(f"❗ 상세 페이지 오류: {e}")
                                continue
                except Exception as e:
                    print(f"❗ {i}페이지 오류: {e}")

            try:
                next_btn = await page.query_selector('a.edge_nav.nav_next')
                if next_btn and await next_btn.is_visible():
                    await next_btn.click()
                    await page.wait_for_timeout(2000)
                else:
                    print("✅ 마지막 페이지 세트 도달")
                    break
            except Exception as e:
                print(f"❗ 다음 세트 이동 실패: {e}")
                break

        await browser.close()

        if results:
            file_index += 1
            filename = f"{base_filename}_{file_index}_last.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=4)
            print(f"✅ 마지막 저장 완료 → {filename}")

async def main():
    for category in CATEGORY_LIST:
        await scrape_category(category["id"], category["name"])

# ▶ 실행
asyncio.run(main())