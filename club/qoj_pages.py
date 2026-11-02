"""Read QOJ's localized profiles and privacy-preserving submission tables."""
import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from .platform_sync import SyncError


def page(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(' ', strip=True).casefold() if soup.title else ''
    if 'just a moment' in title or soup.select_one('#challenge-form, #cf-challenge-running'):
        raise SyncError('QOJ 返回访问验证页面，未读取到题目；请检查服务器访问状态')
    if soup.select_one('input[name=password]') or 'must now be logged in' in html.lower():
        raise SyncError('请更新 QOJ Cookie')
    return soup


def profile_rating(html, account):
    soup = page(html)
    # QOJ labels Rating as “积分” in Chinese; the username metadata is stable.
    names = soup.select('h1 .uoj-username, h2 .uoj-username')
    own = next((node for node in names
                if (node.get('data-nickname') or node.get_text(strip=True)).casefold() == account.casefold()), None)
    if own is None:
        raise SyncError('未识别到绑定账号的 QOJ 个人页，已保留上次资料')
    value = own.get('data-rating', '')
    if own.get('data-rated') != '0' and re.fullmatch(r'-?\d+', value):
        return int(value)
    for item in soup.select('.list-group-item'):
        heading = item.select_one('.list-group-item-heading')
        value = item.select_one('.list-group-item-text')
        if heading and value and heading.get_text(strip=True).rstrip(':：').casefold() in {'rating', '积分'}:
            number = value.get_text(strip=True).replace(',', '')
            if re.fullmatch(r'-?\d+', number):
                return int(number)
    return None


def accepted_rows(html, account):
    soup = page(html)
    problem_path = re.compile(r'/(?:contest/\d+/)?problem/(\d+)/?$')

    def problem_link(row):
        for link in row.select('a[href]'):
            url = urlsplit(link['href'])
            if url.netloc not in {'', 'qoj.ac'}:
                continue
            match = problem_path.fullmatch(url.path)
            if match:
                return link, match[1]
        return None

    table = None
    result_column = None
    for candidate in soup.select('table'):
        headers = [cell.get_text(' ', strip=True).casefold() for cell in candidate.select('tr th')]
        if any(h in {'problem', '题目'} for h in headers) and any(h in {'submitter', '提交者'} for h in headers):
            table = candidate
            result_column = next((i for i, h in enumerate(headers) if h in {'result', 'score', '结果', '得分', '分数', '评测结果'}), None)
            break
    if table is None:
        # Also support the older compact table, which did not expose headings.
        table = next((candidate for candidate in soup.select('table')
                      if any(problem_link(row) for row in candidate.select('tr'))), None)
    if table is None:
        raise SyncError('未识别到 QOJ 提交记录表，未将本次结果计为零题')

    accepted = []
    own_rows = 0
    foreign_rows = 0
    verdict = re.compile(r'(?:AC\s*✓?|Accepted|100(?:\.0+)?(?:\s*(?:分|points|✓))?)', re.I)
    for row in table.select('tr'):
        problem = problem_link(row)
        if problem is None:
            continue
        users = {unquote(urlsplit(a['href']).path.rstrip('/').rsplit('/', 1)[-1]).casefold()
                 for a in row.select('a[href*="/user/profile/"]')}
        users.update((node.get('data-nickname') or node.get_text(strip=True)).casefold()
                     for node in row.select('.uoj-username'))
        if not users:
            raise SyncError('未识别到 QOJ 提交者字段，未覆盖已有记录')
        if account.casefold() not in users:
            foreign_rows += 1
            continue
        own_rows += 1
        cells = row.find_all('td', recursive=False)
        results = [cells[result_column]] if result_column is not None and result_column < len(cells) else cells
        if any(verdict.fullmatch(cell.get_text(' ', strip=True)) for cell in results):
            accepted.append((row, problem[0], problem[1]))
    if foreign_rows and not own_rows:
        raise SyncError('QOJ 返回的提交者与绑定账号不一致，未覆盖已有记录')
    return soup, accepted
