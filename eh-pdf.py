#!/usr/bin/python3
"""
  EH-PDF: Download manga from E-Hentai and export to PDF, for Kindle and iPad！
▼ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  How it works:
   1. 使用你提供的登入 cookies 抓取指定的畫廊頁面的信息
   2. 一個畫廊可能包含很多圖片，因此縮略圖會分好多頁來顯示。
      程序將會從畫廊頁面的第一頁得知總共有多少頁的縮略圖
   3. 逐頁地分析這些縮略圖的頁面，並且從中抽取出每一圖片頁的連結
   4. 同時創建多個異步任務，並行抓取這些圖片頁連結，得到真正的圖片的 URL 地址，
      然後下載這張圖片
   5. 全部完成後，根據設定的參數對圖片進行處理，然後轉換成 PDF

  以上所述的每一步完成之後程序都會將目前的狀態保存到一個 JSON 文件中，以便程序中斷重啓後
  從上次結束的地方開始。因此這個程序可以在運行的中途隨時退出，進度不會丟失。
"""
import aiohttp
import argparse
import asyncio
import io
import json
import logging
import os
import re
import sys

import PIL.Image
import PIL.ImageOps
from PIL import Image, ImageEnhance

CURRENT_DIR = os.getcwd()
# ━━━━━━━━━━━━━━━━━━
# ▼ The directory for saving temporary image files and metadata
# ━━━━━━━━━━━━━━━━━━
APP_DIR: str = ''
EX_API = 'https://exhentai.org/api.php'
EH_API = 'https://api.e-hentai.org/api.php'
# ━━━━━━━━━━━━━━━━━━
# ▼ New EH cookies scheme. You may want to add the igneous field
# ━━━━━━━━━━━━━━━━━━
EH_COOKIES = {
    'ipb_member_id': '3000000',
    'ipb_pass_hash': 'aaaaabbbbbcccccdddddeeeeefffffgg',
    'sk': 'aaaaabbbbbCCCCC1111122222333',
}


async def main():
    mkdir()
    check_cookies()
    if not args.Gallery_URL:
        args.Gallery_URL = input('Please enter a gallery URL:\n')

    logging.debug(f'the url is {args.Gallery_URL}')
    target_gallery = EHGallery(args.Gallery_URL)
    logging.info('正在收集數據，，，')
    await target_gallery.get_metadata()
    await target_gallery.get_each_page_link()
    if not await target_gallery.download_images():
        await asyncio.sleep(1.25)
        return
    # print(target_gallery.page_links)
    if args.pdf:
        target_gallery.create_pdf()

    logging.info('完成力，即將退出')
    await asyncio.sleep(1.25)
    return


def sanitize(filename: str) -> str:
    BLACKLIST = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
    for char in BLACKLIST:
        filename = filename.replace(char, '_')

    if filename[-1] == '.':
        filename += '_'

    return filename


def check_cookies() -> None:
    """
    Check if cookies file exists and load into global variable EH_COOKIES
    :return: None
    """
    global EH_COOKIES
    if not os.path.exists(args.cookies):
        logging.info(
            f'[check_cookies] cookies file does not exist, please check cookies-sample.json and fill your cookies.')
        cookies_sample = open('cookies-sample.json', 'w')
        json.dump(EH_COOKIES, cookies_sample, indent=2)
        cookies_sample.close()
        EH_COOKIES = {}
    else:
        cookies_file = open(args.cookies, 'r')
        EH_COOKIES = json.load(cookies_file)
        logging.info(f'[check_cookies] Loading {args.cookies}')


class EHGallery:
    """
    E-Hentai gallery class, represents an EH gallery and stores metadata.
    """

    # ━━━━━━━━━━━━━━━━━━
    # ▼ https://exhentai.org/g/{gallery_id}/{gallery_token}/
    # ━━━━━━━━━━━━━━━━━━
    gallery_id: str
    gallery_token: str
    is_EX: bool
    # ━━━━━━━━━━━━━━━━━━
    # ▼ How many images contained in this gallery
    # ━━━━━━━━━━━━━━━━━━
    page_count: int
    title: str
    # ━━━━━━━━━━━━━━━━━━
    #   How many web pages used to show the thumbnail images of this gallery.
    # ▼ An account with HATH Perk may have less thumb page count since more thumb images are shown each page
    # ━━━━━━━━━━━━━━━━━━
    thumb_page_count: int
    # ━━━━━━━━━━━━━━━━━━
    #   The web page url of one single image, like this
    # ▼ https://e-hentai.org/s/367d2b44a5/2407775-2
    # ━━━━━━━━━━━━━━━━━━
    page_links: list[str] = []
    # ━━━━━━━━━━━━━━━━━━
    # ▼ The filename saved during image download. For single page, it is like {10: "10.jpg"}
    # ━━━━━━━━━━━━━━━━━━
    local_filenames: dict[str, str] = {}
    working_dir: str = ''

    def __init__(self, url: str):
        # ━━━━━━━━━━━━━━━━━━
        # ▼ Match gallery_id and gallery_token from URL by regex
        # ━━━━━━━━━━━━━━━━━━
        result = re.search(r'https://e([x-])hentai\.org/g/(\d+)/([a-zA-z\d]+)/?$', url)
        if not result:
            logging.error(f'提供的畫廊連結過於惡俗！請按照以下格式：https://exhentai.org/g/2339054/da04b84080/')
            sys.exit(1)
        self.gallery_id = result[2]
        self.gallery_token = result[3]
        self.is_EX = result[1] == 'x'

        # ━━━━━━━━━━━━━━━━━━
        #   The EX URL is given but no cookies file set,
        # ▼ so we change the download source to e-hentai.org
        # ━━━━━━━━━━━━━━━━━━
        if self.is_EX and not EH_COOKIES:
            logging.warning('恁提供了一個 ExHentai 的連結，但是卻沒有提供登入 cookies，'
                            '因此俺會嘗試在 E-Hentai 上搜索對應的畫廊，但是俺不保證成功，，，')
            self.is_EX = False

        # ━━━━━━━━━━━━━━━━━━
        # ▼ find working directory with format <gallery id>-<some random gallery title>
        #   use regex to match the id part
        # ━━━━━━━━━━━━━━━━━━

        working_dir_name_pattern = re.compile(r'([0-9]+)-?.*')
        for i in os.listdir(APP_DIR):
            match = working_dir_name_pattern.match(i)
            if match and match[1] == self.gallery_id:
                self.working_dir = f'{APP_DIR}/{i}'
                logging.debug(f'[__init__] Found existing working directory {self.working_dir}')
                break

        if not self.working_dir:
            self.working_dir = f'{APP_DIR}/{self.gallery_id}'
            os.mkdir(self.working_dir)
            # we will rename the directory after we get the gallery title

        # ━━━━━━━━━━━━━━━━━━
        # ▼ Try to load progress from existing metadata file, to skip the metadata collecting stage
        # ━━━━━━━━━━━━━━━━━━
        self.load_progress()

    def load_progress(self) -> None:
        """
        Read previously collected metadata from metadata.json,
        so we don't have to collect gallery's metadata more than once.
        :return: None
        """
        try:
            progress_file = open(f'{self.working_dir}/metadata.json', 'r', encoding='UTF-8')
            progress = json.load(progress_file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.debug(f'[load_progress_stage1] Error in loading progress, {e}')
            return

        # ━━━━━━━━━━━━━━━━━━
        # ▼ Read known title and page_count
        # ━━━━━━━━━━━━━━━━━━
        try:
            self.title = progress['title']
            self.page_count = progress['page_count']
        except Exception as e:
            logging.debug(f'[load_progress_stage2] Error in loading progress, {e}')
            self.title = ''
            self.page_count = 0

        # ━━━━━━━━━━━━━━━━━━
        # ▼ Read thumb_page_count and page_links
        # ━━━━━━━━━━━━━━━━━━
        try:
            self.thumb_page_count = progress['thumb_page_count']
            self.page_links = progress['page_links']
        except Exception as e:
            logging.debug(f'[load_progress_stage3] Error in loading progress, {e}')
            self.thumb_page_count = 0
            self.page_links = []
            return

        # ━━━━━━━━━━━━━━━━━━
        # ▼ Read the downloaded image files name list for continuous download
        # ━━━━━━━━━━━━━━━━━━
        try:
            self.local_filenames = progress['local_filenames']
        except Exception as e:
            logging.debug(f'[load_progress_stage4] Error in loading progress, {e}')
            self.local_filenames = {}
            return

    def save_progress(self) -> None:
        """
        Save current state object to JSON file, except working directory
        :return: None
        """
        progress = self.__dict__.copy()
        progress.pop('working_dir')
        if self.page_links:
            progress.update({'page_links': self.page_links})

        if self.local_filenames:
            progress.update({'local_filenames': self.local_filenames})

        metadata_file = open(self.working_dir + '/metadata.json', 'w', encoding='UTF-8')
        json.dump(progress, metadata_file, indent=2, ensure_ascii=False)
        metadata_file.close()
        # logging.debug(f'[save_progress] Progress & metadata saved!!')

    def get_gallery_url(self, page: int = 0) -> str:
        """
        Build gallery thumbnail web page url with page count
        :param page: The thumbnail image list page
        :return: like this: https://e-hentai.org/g/2407775/371d8cb5d6/?p=2
        """
        if self.is_EX:
            base_url = 'https://exhentai.org/g/'
        else:
            base_url = 'https://e-hentai.org/g/'
        url = f'{base_url}{self.gallery_id}/{self.gallery_token}/'
        if page:
            url = url + f'?p={page - 1}'
        return url

    async def get_metadata(self) -> None:
        """
        Fetch title and page count from eh-api
        :return: None
        """
        try:
            if self.__getattribute__('title'):
                if self.__getattribute__('page_count'):
                    logging.info('[get_metadata] 正在跳過...')
                    return
        except AttributeError:
            pass

        api_endpoint = EX_API if self.is_EX else EH_API
        payload = {
            "method": "gdata",
            "gidlist": [
                [int(self.gallery_id), self.gallery_token]
            ],
            "namespace": 1
        }

        async with aiohttp.ClientSession(cookies=EH_COOKIES) as session:
            async with session.post(api_endpoint, data=json.dumps(payload)) as resp:
                if resp.status != 200:
                    logging.error(f'無法聯絡 API： {api_endpoint}')
                    sys.exit(1)
                metadata = json.loads(await resp.text())
                logging.debug(metadata)
                if len(metadata) == 0:
                    logging.error(f'無法取得 metadata，cookies 是否正確？')
                    sys.exit(1)

                try:
                    self.title = metadata['gmetadata'][0]['title']
                    self.page_count = int(metadata['gmetadata'][0]['filecount'])
                except KeyError as e:
                    logging.error(f'過於惡俗！ {e}')
                    sys.exit(1)
                try:
                    if metadata['gmetadata'][0]['title_jpn']:
                        self.title = metadata['gmetadata'][0]['title_jpn']
                except (KeyError, IndexError):
                    logging.debug(f'Cannot find JPN title')
                    pass
                logging.info(f'[get_metadata] pages:{self.page_count}, title:{self.title}')
        self.save_progress()

        # rename working directory with title
        if self.title:
            logging.debug(f'[get_metadata] Renaming working directory with title: {self.title}')
            os.rename(self.working_dir, f'{self.working_dir}-{sanitize(self.title)}')
            self.working_dir = f'{self.working_dir}-{sanitize(self.title)}'

    async def get_each_page_link(self) -> None:
        """
        Get each image page link from thumbnail pages.
        Like this: https://e-hentai.org/s/367d2b44a5/2407775-2
        :return: None
        """
        # ━━━━━━━━━━━━━━━━━━
        # ▼ Get thumb page count first
        # ━━━━━━━━━━━━━━━━━━
        try:
            if self.__getattribute__('thumb_page_count'):
                if self.__getattribute__('page_links'):
                    logging.info('[get_each_page_link] 正在跳過...')
                    return
        except AttributeError:
            pass

        # ━━━━━━━━━━━━━━━━━━
        # ▼ Functions copied from GitHub, to extract some info from EH html
        # ━━━━━━━━━━━━━━━━━━
        def count_td_in_html(page_html: str) -> int:
            pattern = re.compile(r'<td.*?>', re.S)
            all_td = pattern.findall(page_html)
            return len(all_td)

        def get_thumb_page_count(page_html: str) -> int:
            target_table = extract_info(page_html, '<table class="ptt".*?</table>')
            return count_td_in_html(target_table) - 2

        def extract_page_urls(page_html: str):
            pattern = re.compile(r'<div class="gdt.*?</a>', re.S)
            all_div = pattern.findall(page_html)
            page_urls = []
            for div in all_div:
                a_tag = extract_info(div, "<a href=.*?>")
                urls.append(a_tag.split('"')[1])
            return page_urls

        async with aiohttp.ClientSession(cookies=EH_COOKIES) as session:
            async with session.get(self.get_gallery_url(), allow_redirects=False) as resp:
                if resp.status != 200:
                    logging.error(f'[get_thumb_page_count] 無法打開畫廊連結！！')
                    sys.exit(1)
                html = await resp.text(encoding='UTF-8')
                self.thumb_page_count = get_thumb_page_count(html)
                logging.debug(f'縮略圖頁共有 {self.thumb_page_count} 頁')
            self.save_progress()

            logging.info(f'[get_each_page_link] 正在從縮略圖頁面中提取畫廊頁面，，，')
            urls: list[str] = []
            for p in range(1, self.thumb_page_count + 1):
                print(f'\r處理中： {p}/{self.thumb_page_count}', end='')
                async with session.get(self.get_gallery_url(p), allow_redirects=False) as resp:
                    if resp.status != 200:
                        logging.error(f'[get_thumb_page_count] 在提取第 {p} 頁時出錯！')
                        sys.exit(1)
                    html = await resp.text(encoding='UTF-8')
                    urls += extract_page_urls(html)

        print('')
        logging.info(f'[get_each_page_link] 成功提取了 {len(urls)} 個項目')
        assert len(urls) == self.page_count
        self.page_links = urls
        self.save_progress()

    async def download_images(self) -> bool:
        """
        In responsible for keep track of download workers.
        :return: True for all success, False for error occurred.
        """
        try:
            os.mkdir(f'{self.working_dir}/download-{sanitize(self.title)}')
        except FileExistsError:
            pass
        download_dir = f'{self.working_dir}/download-{sanitize(self.title)}'

        # ━━━━━━━━━━━━━━━━━━
        # ▼ 創建幾個列表，用來維護負責每一頁的 worker 的狀態。
        # ━━━━━━━━━━━━━━━━━━
        to_dl: list[int] = list(range(self.page_count))
        dl_ing: list[int] = []
        dl_ok: list[int] = []
        dl_failed: list[int] = []

        # ━━━━━━━━━━━━━━━━━━
        # ▼ 搜索下載目錄，確定已經下載完成的文件來實現斷點續傳
        # ━━━━━━━━━━━━━━━━━━
        filelist = os.listdir(download_dir)
        for filename in filelist:
            result = re.search(r'^(\d+)\.[a-zA-Z]{3,5}$', filename)
            if result and (0 <= int(result[1]) < self.page_count):
                dl_ok.append(int(result[1]))
                to_dl.remove(int(result[1]))

        logging.info(f'[download_images] 我們還有 {len(to_dl)} 個需要下載。')
        # ━━━━━━━━━━━━━━━━━━
        # ▼ 允許最大的同時進行的下載任務數
        # ━━━━━━━━━━━━━━━━━━
        MAX_CONCURRENT_TASKS = args.jobs
        WORKER_POOL = []

        # ━━━━━━━━━━━━━━━━━━
        # ▼ 用來從 worker 收集狀態數據的同步隊列
        # ━━━━━━━━━━━━━━━━━━
        queue = asyncio.Queue()
        print(f'\r下載中： {len(dl_ok) + len(dl_failed)}/{self.page_count}', end='')

        # ━━━━━━━━━━━━━━━━━━
        # ▼ 創建一個 http session 並且復用，用來抓取每一圖片頁。
        # ━━━━━━━━━━━━━━━━━━
        async with aiohttp.ClientSession(cookies=EH_COOKIES) as main_site_session:
            # access the top page of gallery to garther hath perk cookies
            async with main_site_session.get(self.get_gallery_url(), allow_redirects=False) as resp:
                if resp.status != 200:
                    logging.error(f'[download_images] 無法打開畫廊連結！！')
                    sys.exit(1)
                set_cookies = resp.cookies
                logging.debug(f'[download_images] 成功獲取 hath perk cookies {set_cookies}')

            while len(to_dl) or len(dl_ing):
                while len(WORKER_POOL) < MAX_CONCURRENT_TASKS and len(to_dl) != 0:
                    this_index = to_dl[0]
                    # ━━━━━━━━━━━━━━━━━━
                    #   HTTP2 session 復用的思想，
                    # ▼ 這個 session 要傳給 worker 用，不然會因爲 session 過多觸發 EH 的 rate limit
                    # ━━━━━━━━━━━━━━━━━━
                    asyncio.create_task(self.download_worker(this_index, queue, main_site_session))
                    WORKER_POOL.append(this_index)
                    to_dl.remove(this_index)
                    dl_ing.append(this_index)
                try:
                    # ━━━━━━━━━━━━━━━━━━
                    # {
                    #   'index': index,
                    #   'success': True,
                    #   'filename': f'{index}{suffix}'
                    # }
                    # ▼ 傳遞的消息格式
                    # ━━━━━━━━━━━━━━━━━━
                    message = queue.get_nowait()
                    if message['success']:
                        dl_ok.append(message['index'])
                        self.local_filenames.update({str(message['index']): message['filename']})
                        self.save_progress()
                    else:
                        dl_failed.append(message['index'])
                    dl_ing.remove(message['index'])
                    WORKER_POOL.remove(message['index'])
                    print(f'\r下載中： {len(dl_ok) + len(dl_failed)}/{self.page_count}', end='')
                except asyncio.queues.QueueEmpty:
                    await asyncio.sleep(0.1)

        print('')
        logging.info(
            f'[download_images] 完成力，總共 {self.page_count} 個，成功 {len(dl_ok)} 個，失敗 {len(dl_failed)} 個')
        if len(dl_failed):
            logging.warning(f'[download_images] 失敗了 {len(dl_failed)} 個，請重新運行一次本程序！')
            return False
        return True

    async def download_worker(self, index: int, queue: asyncio.Queue, main_site_session: aiohttp.ClientSession) -> None:
        """
        The real part of executing download task
        :param index: 畫廊的第 x 頁，從 0 開始。
        :param queue: 用來通信的同步隊列
        :param main_site_session: 用來訪問 EH 圖片頁的 session
        :return: None
        """
        page_url = self.page_links[index]
        secondary_nl_id = ''
        retry = 0
        while retry < 3:
            if retry:
                logging.warning(f'\r[download_worker] #{index} 連線失敗！正在重試第 {retry} 次... {secondary_nl_id}')
            try:
                # ━━━━━━━━━━━━━━━━━━
                # ▼ 復用之前的 session，避免觸發 EH 主站的 rate limit
                # ━━━━━━━━━━━━━━━━━━
                async with main_site_session.get(f'{page_url}?nl={secondary_nl_id}', allow_redirects=False) as resp:
                    if resp.status != 200:
                        logging.error(f'\r[download_worker] #{index} E-Hentai 無法打開！!!')
                        await queue.put({'index': index, 'success': False})
                        return

                    html = await resp.text()
                    target_img_url = extract_info(html, '<img id=.*?>').split('"')[3]
                    # extract secondary_nl_id from <a id="loadfail" onclick="return nl('secondary id')"
                    secondary_nl_id = extract_info(html, 'id="loadfail" onclick="return nl.*?"').split("'")[1]
                    if not target_img_url:
                        logging.error(f'\r[download_worker] #{index} target image {target_img_url} 過於惡俗！！')
                        await queue.put({'index': index, 'success': False})
                        return

                # ━━━━━━━━━━━━━━━━━━
                # ▼ 圖片文件存在域 Hentai@Home 系統上面，因此新開 session，先將下載數據暫存在內存
                # ━━━━━━━━━━━━━━━━━━
                session_timeout = aiohttp.ClientTimeout(total=None,
                                                        sock_connect=7,
                                                        sock_read=10)
                async with aiohttp.ClientSession(cookies={}, timeout=session_timeout) as session:
                    async with session.get(target_img_url, allow_redirects=False) as resp:
                        if resp.status != 200:
                            logging.error(f'\r[download_worker] #{index} 狀態碼 {resp.status} 過於惡俗！！')
                            await queue.put({'index': index, 'success': False})
                            return

                        mimetype = resp.headers.get('Content-Type')
                        size = resp.headers.get('Content-Length')
                        recv_bytes = await resp.read()
                        if len(recv_bytes) != int(size):
                            logging.error(
                                f'\r[download_worker] #{index} 下載的文件大小 {len(recv_bytes)}（{size}） 過於惡俗！！')
                            await queue.put({'index': index, 'success': False})
                            return

                        # ━━━━━━━━━━━━━━━━━━
                        # ▼ 講下載到內存中的數據寫入本地
                        # ━━━━━━━━━━━━━━━━━━
                        if mimetype == 'image/jpeg':
                            suffix = '.jpg'
                        elif mimetype == 'image/png':
                            suffix = '.png'
                        else:
                            # ━━━━━━━━━━━━━━━━━━
                            # ▼ 不支持 GIF 圖，，，
                            # ━━━━━━━━━━━━━━━━━━
                            logging.error(
                                f'\r[download_worker] #{index} 的 mime type {mimetype} 過於惡俗！！您的 EH 配額是否不足？請前往 '
                                f'https://e-hentai.org/home.php 使用 GP 點重置！')
                            logging.debug(f'\r[download_worker] image page url: {page_url}\nimage: {target_img_url}')
                            await queue.put({'index': index, 'success': False})
                            return

                        local_file = open(f'{self.working_dir}/download-{sanitize(self.title)}/{index}{suffix}', 'wb')
                        local_file.write(recv_bytes)
                        local_file.close()
                        await queue.put({'index': index, 'success': True, 'filename': f'{index}{suffix}'})
                        return
            except (aiohttp.client.ClientError, asyncio.TimeoutError):
                retry += 1
                await asyncio.sleep(1)

        logging.error(f'\r[download_worker] #{index} 連線失敗！請前往 {page_url} 頁面底部點擊修復破損圖片！')
        await queue.put({'index': index, 'success': False})
        return

    def create_pdf(self) -> None:
        """
        從已下載的圖片來創建 PDF
        :return: None
        """
        logging.info(f'[create_pdf] 正在建立 PDF')
        download_dir = f'{self.working_dir}/download-{sanitize(self.title)}'

        images = []
        # ━━━━━━━━━━━━━━━━━━
        # ▼ 統計本地的圖片文件列表然後順便處理
        # ━━━━━━━━━━━━━━━━━━
        try:
            for index in range(self.page_count):
                modified = image_process(Image.open(f'{download_dir}/{self.local_filenames[str(index)]}'), index == 0)
                images.append(modified)

        except KeyError as e:
            logging.error(f'[create_pdf] {e} 數據已損壞，請刪除下載目錄中的內容並重新下載，，，')
            sys.exit(1)

        pdf_path = args.output or f'{CURRENT_DIR}/{sanitize(self.title)}.pdf'
        pdf_path = os.path.abspath(pdf_path)
        try:
            images[0].save(
                pdf_path, "PDF",
                resolution=96,
                save_all=True,
                append_images=images[1:],
            )
        except PermissionError:
            logging.error(f'[create_pdf] 無法儲存到 {pdf_path}，請檢查文件是否被佔用以及權限是否正常')
            sys.exit(1)

        logging.info(f'[create_pdf] PDF 建立完成，牠就在 {pdf_path}！')


def image_process(image: Image, first=False) -> Image:
    """
    根據參數處理圖片文件
    :param image: PIL 的 Image 對象
    :param first: 是否是第一頁？
    :return: 處理後的 Image 對象
    """
    new_image = image
    new_image.load()

    # ━━━━━━━━━━━━━━━━━━
    # ▼ 消除透明度通道，因爲 PDF 不支持
    # ━━━━━━━━━━━━━━━━━━
    if new_image.mode == "RGBA":
        logging.debug(f'[image_process] RGBA 轉換成 RGB')

        background = Image.new("RGB", new_image.size, (255, 255, 255))
        background.paste(new_image, mask=new_image.split()[3])  # 3 is the alpha channel

        new_image = background

    if new_image.mode == "P":
        logging.debug(f'[image_process] P 模式轉換成 RGB')
        new_image = new_image.convert("RGB")

    # ━━━━━━━━━━━━━━━━━━
    # ▼ 封面圖不轉換成灰度，而其他的轉換
    # ━━━━━━━━━━━━━━━━━━
    if args.greyscale and not first:
        logging.debug(f'[image_process] 轉換成灰度')
        new_image = PIL.ImageOps.grayscale(new_image)
        enhancer = ImageEnhance.Contrast(new_image)
        new_image = enhancer.enhance(1.25)

    # ━━━━━━━━━━━━━━━━━━
    # ▼ 根據最大圖像尺寸縮放圖片
    # ━━━━━━━━━━━━━━━━━━
    if args.max_x or args.max_y:
        logging.debug(f'[image_process] 縮放大小到 {args.max_x}x{args.max_y}')
        if args.max_x is None:
            args.max_x = 99999
        if args.max_y is None:
            args.max_y = 99999
        new_image.thumbnail((args.max_x, args.max_y), resample=PIL.Image.LANCZOS)

    buffer = io.BytesIO()
    new_image.save(buffer, 'jpeg', quality=90)
    buffer.flush()
    new_image.close()
    buffer.seek(0)

    return Image.open(buffer)


def extract_info(content: str, regexp: str) -> str:
    """
    根據規則運算式來從原文中提取指定內容的 wrap 函數
    :param content: 原文
    :param regexp: 規則運算式
    :return: 匹配到的內容
    """
    pattern = re.compile(regexp, re.S)
    match = pattern.search(content)
    if match:
        return match.group()
    else:
        return ''


def mkdir() -> None:
    """
    創建工作時用的臨時文件夾
    :return: None
    """
    global APP_DIR
    try:
        os.mkdir('EH-Downloader')
    except FileExistsError:
        pass
    APP_DIR = CURRENT_DIR + '/EH-Downloader'


if __name__ == '__main__':
    # ━━━━━━━━━━━━━━━━━━
    # ▼ 檢查輸入參數
    # ━━━━━━━━━━━━━━━━━━
    parser = argparse.ArgumentParser(prog='eh-pdf.py',
                                     description='Download EH artwork to PDF for your Kindle or iPad')
    parser.add_argument('-c', '--cookies', default='cookies.json', help='Your EH login cookies file')
    parser.add_argument('-g', '--greyscale',
                        action='store_true',
                        help='轉換成灰度並稍微提高對比度，方便使用 Kindle 觀看')
    parser.add_argument('-x', '--max-x', type=int,
                        help='The max width in pixels of the PDF image, useful to reduce file size for Kindle')
    parser.add_argument('-y', '--max-y', type=int,
                        help='The max height in pixels of the PDF image, useful to reduce file size for Kindle')
    parser.add_argument('-o', '--output', help='The output path/filename of PDF file')
    parser.add_argument('-j', '--jobs', type=int, default=32, help='允許多線程下載的最多線程，默認 32')
    parser.add_argument('-d', '--debug', action='store_true', help='Debug 模式，讓日誌輸出更加羅嗦')
    parser.add_argument('-p', '--pdf', action='store_true', help='將下載的圖片合併成 PDF 文件')
    parser.add_argument('Gallery_URL', help='The EH gallery URL to download.', default='', nargs='?', const=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S'
                        )

    logging.debug(args)
    if args.jobs < 1:
        logging.error(f'線程數量爲 {args.jobs}，過於惡俗！')
        sys.exit(2)

    # ━━━━━━━━━━━━━━━━━━
    # ▼ Let's roll!
    # ━━━━━━━━━━━━━━━━━━
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # give a hint to user to rerun the command with all the same arguments
        logging.warning(f'您中斷了操作！您可以重新執行該命令 {sys.argv[0]} {args.Gallery_URL}')
        sys.exit(1)
