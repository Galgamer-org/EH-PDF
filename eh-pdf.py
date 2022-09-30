#!/usr/bin/python3
import asyncio, logging, re, aiohttp, argparse, json, os, io, sys

import PIL.Image, PIL.ImageOps
from PIL import Image, ImageEnhance

CURRENT_DIR = os.getcwd()
APP_DIR: str = ''
EX_API = 'https://exhentai.org/api.php'
EH_API = 'https://api.e-hentai.org/api.php'
EH_COOKIES = {
    'ipb_member_id': '3000000',
    'ipb_pass_hash': 'aaaaabbbbbcccccdddddeeeeefffffgg',
    'igneous': 'e12345678',
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
    await target_gallery.download_images()
    # print(target_gallery.page_links)
    target_gallery.create_pdf()
    input('完成力，請按 Enter 鍵退出')
    await asyncio.sleep(0.25)
    return


def check_cookies():
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


class EHGallery():
    gallery_id: str
    gallery_token: str
    is_EX: bool
    page_count: int
    title: str
    thumb_page_count: int
    page_links: [str] = []
    local_filenames: {int: str} = {}
    working_dir: str

    def __init__(self, url: str):
        result = re.search(r'https://e([x-])hentai\.org/g/(\d+)/([a-zA-z\d]+)/?$', url)
        if not result:
            logging.error(f'提供的畫廊連結過於惡俗！請按照以下格式：https://exhentai.org/g/2339054/da04b84080/')
            sys.exit(1)
        self.gallery_id = result[2]
        self.gallery_token = result[3]
        self.is_EX = result[1] == 'x'

        if self.is_EX and not EH_COOKIES:
            logging.warning('恁提供了一個 ExHentai 的連結，但是卻沒有提供登入 cookies，'
                            '因此俺會嘗試在 E-Hentai 上搜索對應的畫廊，但是俺不保證成功，，，')
            self.is_EX = False

        try:
            os.mkdir(f'{APP_DIR}/{self.gallery_id}')
        except FileExistsError:
            pass

        self.working_dir = f'{APP_DIR}/{self.gallery_id}'
        self.load_progress()

    def load_progress(self):
        try:
            progress_file = open(f'{self.working_dir}/metadata.json', 'r', encoding='UTF-8')
            progress = json.load(progress_file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.debug(f'[load_progress_stage1] Error in loading progress, {e}')
            return

        try:
            self.title = progress['title']
            self.page_count = progress['page_count']
        except Exception as e:
            logging.debug(f'[load_progress_stage2] Error in loading progress, {e}')
            self.title = ''
            self.page_count = 0

        try:
            self.thumb_page_count = progress['thumb_page_count']
            self.page_links = progress['page_links']
        except Exception as e:
            logging.debug(f'[load_progress_stage3] Error in loading progress, {e}')
            self.thumb_page_count = 0
            self.page_links = []
            return

        try:
            self.local_filenames = progress['local_filenames']
        except Exception as e:
            logging.debug(f'[load_progress_stage4] Error in loading progress, {e}')
            self.local_filenames = {}
            return

    def save_progress(self):
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

    def get_gallery_url(self, page: int = 0):
        if self.is_EX:
            base_url = 'https://exhentai.org/g/'
        else:
            base_url = 'https://e-hentai.org/g/'
        url = f'{base_url}{self.gallery_id}/{self.gallery_token}/'
        if page:
            url = url + f'?p={page - 1}'
        return url

    async def get_metadata(self):
        '''
        Fetch title and page count from ehapi
        :return: None
        '''
        try:
            if self.__getattribute__('title'):
                if self.__getattribute__('page_count'):
                    logging.info('[get_metadata] 正在跳過...')
                    return
        except AttributeError:
            pass

        API = EX_API if self.is_EX else EH_API
        payload = {
            "method": "gdata",
            "gidlist": [
                [int(self.gallery_id), self.gallery_token]
            ],
            "namespace": 1
        }

        async with aiohttp.ClientSession(cookies=EH_COOKIES) as session:
            async with session.post(API, data=json.dumps(payload)) as resp:
                if resp.status != 200:
                    logging.error(f'無法聯絡 API： {API}')
                    sys.exit(1)
                metadata = json.loads(await resp.text())
                logging.debug(metadata)
                try:
                    self.title = metadata['gmetadata'][0]['title']
                    self.page_count = int(metadata['gmetadata'][0]['filecount'])
                except KeyError as e:
                    logging.error(f'過於惡俗！ {e}')
                    sys.exit(1)
                try:
                    self.title = metadata['gmetadata'][0]['title_jpn']
                except:
                    logging.debug(f'Cannot find JPN title')
                    pass
                logging.info(f'[get_metadata] pages:{self.page_count}, title:{self.title}')
        self.save_progress()

    async def get_each_page_link(self):
        # get thumb page count first
        try:
            if self.__getattribute__('thumb_page_count'):
                if self.__getattribute__('page_links'):
                    logging.info('[get_each_page_link] 正在跳過...')
                    return
        except AttributeError:
            pass

        def count_td_in_html(html: str) -> int:
            pattern = re.compile(r'<td.*?>', re.S)
            allTd = pattern.findall(html)
            return len(allTd)

        def get_thumb_page_count(html: str) -> int:
            targetTable = extract_info(html, '<table class="ptt".*?</table>')
            return count_td_in_html(targetTable) - 2

        def extract_page_urls(page_html: str):
            pattern = re.compile(r'<div class="gdt.*?</a>', re.S)
            all_div = pattern.findall(page_html)
            urls = []
            for div in all_div:
                aTag = extract_info(div, "<a href=.*?>")
                urls.append(aTag.split('"')[1])
            return urls

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
            urls: [str] = []
            for p in range(1, self.thumb_page_count + 1):
                print(f'\r處理中： {p}/{self.thumb_page_count}', end='')
                async with session.get(self.get_gallery_url(p), allow_redirects=False) as resp:
                    if resp.status != 200:
                        logging.error(f'[get_thumb_page_count] 在提取第 {p} 頁時出錯！')
                        sys.exit(1)
                    html = await resp.text(encoding='UTF-8')
                    urls += extract_page_urls(html)

        print('\n')
        logging.info(f'[get_each_page_link] 成功提取了 {len(urls)} 個項目')
        assert len(urls) == self.page_count
        self.page_links = urls
        self.save_progress()

    async def download_images(self):
        # make download dir
        try:
            os.mkdir(f'{self.working_dir}/download')
        except FileExistsError:
            pass
        download_dir = f'{self.working_dir}/download'

        to_dl: [int] = list(range(self.page_count))
        dl_ing: [int] = []
        dl_ok: [int] = []
        dl_failed: [int] = []

        # search for download dir
        filelist = os.listdir(download_dir)
        for filename in filelist:
            result = re.search(r'^(\d+)\.[a-zA-Z]{3,5}$', filename)
            if result and (0 <= int(result[1]) < self.page_count):
                dl_ok.append(int(result[1]))
                to_dl.remove(int(result[1]))

        logging.info(f'[download_images] 我們還有 {len(to_dl)} 個需要下載。')
        MAX_CONCURRENT_TASKS = args.j
        WORKER_POOL = []

        queue = asyncio.Queue()
        print(f'\r下載中： {len(dl_ok) + len(dl_failed)}/{self.page_count}', end='')
        while len(to_dl) or len(dl_ing):
            while len(WORKER_POOL) < MAX_CONCURRENT_TASKS and len(to_dl) != 0:
                this_index = to_dl[0]
                asyncio.create_task(self.download_worker(this_index, queue))
                WORKER_POOL.append(this_index)
                to_dl.remove(this_index)
                dl_ing.append(this_index)
            try:
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
            sys.exit(1)
        return

    async def download_worker(self, index: int, queue: asyncio.Queue):
        page_url = self.page_links[index]
        try:
            async with aiohttp.ClientSession(cookies=EH_COOKIES) as session:
                async with session.get(page_url, allow_redirects=False) as resp:
                    if resp.status != 200:
                        logging.error(f'[download_worker] #{index} error occurred!!')
                        await queue.put({'index': index, 'success': False})
                        return

                    html = await resp.text()
                    target_img_url = extract_info(html, '<img id=.*?>').split('"')[3]
                    if not target_img_url:
                        logging.error(f'[download_worker] #{index} target image {target_img_url} 過於惡俗！！')
                        await queue.put({'index': index, 'success': False})
                        return

            async with aiohttp.ClientSession(cookies={}) as session:
                async with session.get(target_img_url, allow_redirects=False) as resp:
                    if resp.status != 200:
                        logging.error(f'[download_worker] #{index} 狀態碼 {resp.status} 過於惡俗！！')
                        await queue.put({'index': index, 'success': False})
                        return

                    mimetype = resp.headers.get('Content-Type')
                    size = resp.headers.get('Content-Length')
                    bytes = await resp.read()
                    if len(bytes) != int(size):
                        logging.error(f'[download_worker] #{index} 下載的文件大小 {len(bytes)}（{size}） 過於惡俗！！')
                        await queue.put({'index': index, 'success': False})
                        return

                    # write to file
                    if mimetype == 'image/jpeg':
                        suffix = '.jpg'
                    elif mimetype == 'image/png':
                        suffix = '.png'
                    else:
                        logging.error(f'[download_worker] #{index} 的 mime type {mimetype} 過於惡俗！！')
                        await queue.put({'index': index, 'success': False})
                        return

                    local_file = open(f'{self.working_dir}/download/{index}{suffix}', 'wb')
                    local_file.write(bytes)
                    local_file.close()
                    await queue.put({'index': index, 'success': True, 'filename': f'{index}{suffix}'})
                    return
        except (aiohttp.client.ClientError, asyncio.TimeoutError):
            logging.error(f'[download_worker] #{index} 連線失敗！')
            await queue.put({'index': index, 'success': False})
            return

    def create_pdf(self):
        logging.info(f'[create_pdf] 正在建立 PDF')
        download_dir = f'{self.working_dir}/download'

        # search for download dir
        # paths: [int] = []
        # filelist = os.listdir(download_dir)
        # for filename in filelist:
        #     result = re.search(r'^(\d+)\.[a-zA-Z]{3,5}$', filename)
        #     if result and (0 <= int(result[1]) < self.page_count):
        #         paths.append(f'{self.working_dir}/download/{filename}')

        images = []
        try:
            for index in range(self.page_count):
                modified = image_process(Image.open(f'{download_dir}/{self.local_filenames[str(index)]}'), index == 0)
                images.append(modified)

        except KeyError as e:
            logging.error(f'[create_pdf] {e} 數據已損壞，請刪除下載目錄中的內容並重新下載，，，')
            sys.exit(1)

        pdf_path = args.output or f'{CURRENT_DIR}/{self.title}.pdf'
        try:
            images[0].save(
                pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:]
            )
        except PermissionError:
            logging.error(f'[create_pdf] 無法儲存到 {pdf_path}，請檢查文件是否被佔用以及權限是否正常')
            sys.exit(1)

        logging.info(f'[create_pdf] PDF 建立完成，牠就在 {pdf_path}！')


def image_process(image: Image, first=False) -> Image:
    new_image = image
    new_image.load()

    if new_image.mode == "RGBA":
        logging.debug(f'[image_process] RGBA 轉換成 RGB')

        background = Image.new("RGB", new_image.size, (255, 255, 255))
        background.paste(new_image, mask=new_image.split()[3])  # 3 is the alpha channel

        new_image = background

    if args.greyscale and not first:
        logging.debug(f'[image_process] 轉換成灰度')
        new_image = PIL.ImageOps.grayscale(new_image)
        enhancer = ImageEnhance.Contrast(new_image)
        new_image = enhancer.enhance(1.25)

    if args.max_x or args.max_y:
        logging.debug(f'[image_process] 縮放大小到 {args.max_x}x{args.max_y}')
        if args.max_x is None:
            args.max_x = 99999
        if args.max_y is None:
            args.max_y = 99999
        new_image.thumbnail((args.max_x, args.max_y), resample=PIL.Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    new_image.save(buffer, 'jpeg')
    buffer.flush()
    new_image.close()
    buffer.seek(0)

    return Image.open(buffer)


def extract_info(content: str, regExp: str) -> str:
    pattern = re.compile(regExp, re.S)
    match = pattern.search(content)
    if match:
        return match.group()
    else:
        return ''


def mkdir():
    global APP_DIR
    try:
        os.mkdir('EH-Downloader')
    except FileExistsError:
        pass
    APP_DIR = CURRENT_DIR + '/EH-Downloader'


if __name__ == '__main__':
    # parse arg
    parser = argparse.ArgumentParser(prog='E-Hentai PDF Downloader',
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
    parser.add_argument('-j', type=int, default=12, help='允許多線程下載的最多線程，默認 12')
    parser.add_argument('-d', '--debug', action='store_true', help='Debug 模式，讓日誌輸出更加羅嗦')
    parser.add_argument('Gallery_URL', help='The EH gallery URL to download.', default='', nargs='?', const=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S'
                        )

    logging.debug(args)
    # Let's roll!
    asyncio.run(main())
