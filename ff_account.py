# -*- coding: utf-8 -*-
"""Free Fire guest account creator — used by main panel auto-deploy."""
import os, json, time, uuid, random, asyncio, base64, ssl, hmac, hashlib, string
from datetime import datetime
from typing import Optional, Dict, Any

try:
    import httpx
    import aiohttp
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError:
    httpx = aiohttp = AES = pad = None

try:
    from google_play_scraper import app as play_scraper
except Exception:
    play_scraper = None

try:
    from protobuf_decoder.protobuf_decoder import Parser
except Exception:
    Parser = None

try:
    import reqClan_pb2
    _CLAN_PB_AVAILABLE = True
except Exception:
    _CLAN_PB_AVAILABLE = False

AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
KEYSTREAM = bytes([0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30])
HEX_KEY = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
API_KEY = HEX_KEY.encode()

REGION_LANG = {
    "ME": "ar", "IND": "hi", "ID": "id", "VN": "vi", "TH": "th",
    "BD": "bn", "PK": "ur", "TW": "zh", "RU": "ru", "SAC": "es",
    "BR": "pt", "NA": "pt", "SG": "pt", "US": "pt",
}

DEFAULT_BIO = "[C][B]WEB : MAHIR.XO.JE [FFD700]TG : MAHIR0208"

def _deps_ok():
    return all(x is not None for x in (httpx, aiohttp, AES, pad))

def encode_varint(n: int) -> bytes:
    out = bytearray()
    if n < 0:
        n &= 0xFFFFFFFFFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)

def decode_varint(data, offset):
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if not (byte & 0x80):
            return result, offset
        shift += 7
    return None, offset

def decode_protobuf_2(data):
    result = {}
    offset = 0
    data_len = len(data)
    while offset < data_len:
        header, offset = decode_varint(data, offset)
        if header is None:
            break
        fn = header >> 3
        wt = header & 0x7
        if wt == 0:
            v, offset = decode_varint(data, offset)
            if v is not None:
                result[fn] = v
        elif wt == 2:
            length, offset = decode_varint(data, offset)
            if length is None:
                break
            value = data[offset:offset + length]
            offset += length
            try:
                s = value.decode('utf-8')
                result[fn] = s if s else value.hex()
            except UnicodeDecodeError:
                nested = decode_protobuf_2(value)
                result[fn] = nested if nested else value.hex()
        elif wt == 1:
            offset += 8
        elif wt == 3:
            offset += 4
        else:
            break
    return result

def _parse_results_sync(results):
    out = {}
    for r in results:
        fd = {"wire_type": r.wire_type}
        if r.wire_type == "varint":
            fd["data"] = r.data
        elif r.wire_type in ("string", "bytes"):
            fd["data"] = r.data
        elif r.wire_type == "length_delimited":
            if hasattr(r.data, "results"):
                fd["data"] = _parse_results_sync(r.data.results)
            elif isinstance(r.data, list):
                fd["data"] = _parse_results_sync(r.data)
            else:
                fd["data"] = str(r.data)
        out[str(r.field)] = fd
    return out

def decode_protobuf_dict(data: bytes) -> dict:
    if Parser is None:
        return {}
    try:
        parsed = Parser().parse(data)
        return _parse_results_sync(parsed)
    except Exception:
        return {}

def _encode_proto_std(fields):
    out = b""
    for f in sorted(fields.keys()):
        v = fields[f]
        if isinstance(v, bool):
            out += encode_varint((f << 3) | 0) + encode_varint(int(v))
        elif isinstance(v, int):
            out += encode_varint((f << 3) | 0) + encode_varint(v)
        elif isinstance(v, (str, bytes)):
            if isinstance(v, str):
                v = v.encode()
            out += encode_varint((f << 3) | 2) + encode_varint(len(v)) + v
    return out

def create_proto(fields) -> bytes:
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(field, str):
            field = int(field)
        if isinstance(value, dict):
            nested = create_proto(value)
            packet.extend(encode_varint((field << 3) | 2) + encode_varint(len(nested)) + nested)
        elif isinstance(value, bool):
            packet.extend(encode_varint((field << 3) | 0) + encode_varint(1 if value else 0))
        elif isinstance(value, int):
            packet.extend(encode_varint((field << 3) | 0) + encode_varint(value))
        elif isinstance(value, str):
            enc = value.encode()
            packet.extend(encode_varint((field << 3) | 2) + encode_varint(len(enc)) + enc)
        elif isinstance(value, (bytes, bytearray)):
            packet.extend(encode_varint((field << 3) | 2) + encode_varint(len(value)) + value)
    return bytes(packet)

def encrypt_aes(hex_data: str) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(bytes.fromhex(hex_data), AES.block_size)).hex()

def get_app_version():
    try:
        if play_scraper:
            return play_scraper('com.dts.freefireth').get('version')
    except Exception:
        pass
    return "1.132.9"

def generate_signature(payload_str):
    return hmac.new(API_KEY, payload_str.encode(), hashlib.sha256).hexdigest()

_client = None
def _get_client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(verify=False, timeout=15.0)
    return _client

async def version_config(region="BD"):
    app_version = get_app_version()
    lang = REGION_LANG.get(region.upper(), "en")
    url = (
        f"https://version.ggwhitehawk.com/live/ver.php?version={app_version}&lang={lang}"
        f"&device=android&channel=android&appstore=googleplay&region={region.upper()}"
        f"&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
    )
    try:
        r = await _get_client().get(url)
        j = r.json()
        server_url = j.get("server_url")
        remote_version = j.get("remote_version")
        latest_release_version = j.get("latest_release_version")
        gops = [u.strip() for u in j.get("gop_url", "").split(";") if u.strip()]
        gop_1 = gops[0] if gops else "https://ffmconnect.ppmainecoonghj.com"
        if not server_url:
            return None
        return latest_release_version, remote_version, server_url, gop_1, app_version
    except Exception:
        return None

async def register_account(password, gop_url, app_version):
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    payload = json.dumps(
        {"app_id": 100067, "client_type": 2, "password": password, "source": 2},
        separators=(',', ':'),
    )
    headers = {
        "User-Agent": f"GarenaMSDK/4.0.44(SM-E135F ;Android 14;en;GB;app {app_version} 2019118525;)",
        "Authorization": f"Signature {generate_signature(payload)}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        async with aiohttp.ClientSession(connector=connector) as s:
            async with s.post(
                f"{gop_url}/api/v2/oauth/guest:register",
                headers=headers, data=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = json.loads(await resp.text())
                if data.get("code") == 0:
                    return data["data"]["uid"]
    except Exception:
        pass
    return None

async def grant_token(uid, password, gop_url, app_version):
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    payload = json.dumps(
        {
            "client_id": 100067, "client_secret": HEX_KEY, "client_type": 2,
            "device_id": f"02-{uuid.uuid4()}", "password": password,
            "response_type": "token", "uid": int(uid),
        },
        separators=(',', ':'),
    )
    headers = {
        "User-Agent": f"GarenaMSDK/4.0.44(SM-E135F ;Android 14;en;GB;app {app_version} 2019118525;)",
        "Authorization": f"Signature {generate_signature(payload)}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        async with aiohttp.ClientSession(connector=connector) as s:
            async with s.post(
                f"{gop_url}/api/v2/oauth/guest/token:grant",
                headers=headers, data=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = json.loads(await resp.text())
                if data.get("code") == 0:
                    return data["data"]
    except Exception:
        pass
    return None

async def get_payload(access_token, open_id, platform, version, lang_code="en", region="BD"):
    region = (region or "BD").upper()
    major_login_fields = {
        3: str(datetime.now())[:-7], 4: "free fire", 5: 1, 7: str(version),
        8: "Android OS 11 / API-30 (RP1A.200720.011/230921V810)",
        9: "Handheld", 10: "Grameenphone", 11: "WIFI",
        12: 1708, 13: 750, 14: "480",
        15: "ARM64 FP ASIMD AES | 2000 | 8",
        16: 5767, 17: "Mali-G52 MC2",
        18: "OpenGL ES 3.2 v1.r26p0-01eac0.f143e3f9482527bbad36b3ec27f93e59",
        19: "Google|3f10d414-be33-4ac3-b9fc-fcbf47c183b5",
        20: "103.200.36.134", 21: lang_code or "en", 22: str(open_id), 23: "4", 24: "Handheld",
        25: "INFINIX MOBILITY LIMITED Infinix X6812", 26: region,
        29: str(access_token), 30: 1, 41: "Grameenphone", 42: "WIFI",
        57: "7428b253defc164018c604a1ebbfebdf",
        60: 110962, 61: 80611, 62: 1051, 64: 80829,
        65: 110962, 66: 80829, 67: 110962, 73: 2,
        74: "/data/app/~~MxBbX9YA6AkFscre_RExgw==/com.dts.freefireth-hLOkTeh1Q46L_oLV4UXQTg==/lib/arm64",
        76: 1,
        77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~MxBbX9YA6AkFscre_RExgw==/com.dts.freefireth-hLOkTeh1Q46L_oLV4UXQTg==/base.apk",
        78: 3, 79: 2, 81: "64", 83: "2019121229", 85: 3,
        86: "OpenGLES2", 87: 4095, 88: 4,
        91: {9: 65}, 92: 10508, 93: "android",
        94: "KqsHT76RdsVKvnpkirzc2FQs3eu0OZChfZxMTZn+Rjv06Ri2qeOQkyPcdk5JceWKmXhOFFUPuNy9S8esTr37yCT5piY32iUcehVw0bL4F4lzAmyD",
        95: 111207,
        96: '{"cur_rate":[60,90],"support_etc2":false}',
        97: 1, 98: 1, 99: "4", 100: "4",
        102: "B\\FFP[[\tf", 103: 1, 104: 28754, 105: 1,
        106: "https://dl.ak.freefiremobile.com/live/ABHotUpdates/|https://core-ak.freefiremobile.com/live/ABHotUpdates/|a4332cb1c1a84e51dd77441e4856ed5a",
        107: "1.477aa00e98bf924c"
    }
    get_login_data = dict(major_login_fields)
    get_login_data.update({"90": "Khulna", "91": "D", "99": "0", "103": 1})
    return (
        bytes.fromhex(encrypt_aes(create_proto(major_login_fields).hex())),
        bytes.fromhex(encrypt_aes(create_proto(get_login_data).hex())),
    )

async def major_login(payload, login_url, release_version):
    url = f"{login_url.rstrip('/')}/MajorLogin"
    req_headers = {
        "Accept": "*/*", "Authorization": "Bearer ",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": f"{release_version}",
        "User-Agent": "UnityPlayer/2018.4.12f1",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, headers=req_headers, data=payload, ssl=ssl_context) as response:
                content = await response.read()
                if response.status != 200 or len(content) < 200:
                    return None
                best = None
                best_score = -1
                best_off = 0
                for offset in [64, 0, 48, 32, 80, 16, 128, 8]:
                    if offset >= len(content):
                        continue
                    cand = decode_protobuf_dict(content[offset:]) or {
                        str(k): {"data": v} for k, v in decode_protobuf_2(content[offset:]).items()
                    }
                    keys = set(cand.keys())
                    has_jwt = ("8" in keys) or (8 in keys)
                    has_url = ("10" in keys) or (10 in keys)
                    score = len(cand) + (100 if has_jwt else 0) + (50 if has_url else 0)
                    if score > best_score:
                        best = cand
                        best_score = score
                        best_off = offset
                    if has_jwt and has_url:
                        break
                if not best or ("8" not in best and 8 not in best):
                    return None
                best["__RAW_HEX__"] = content.hex()
                best["__OFFSET__"] = best_off
                return best
    except Exception:
        return None

async def get_login_data(payload, jwt_token, server_url, release_version):
    url = f"{server_url.rstrip('/')}/GetLoginData"
    hdrs = {
        "Accept": "*/*", "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": f"{release_version}",
        "User-Agent": "UnityPlayer/2018.4.12f1",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(url, headers=hdrs, data=payload, ssl=ssl_ctx) as r:
                if r.status != 200:
                    return None
                content = await r.read()
                for off in [0, 64, 48, 32, 80, 16, 128, 8]:
                    if off >= len(content):
                        continue
                    c = decode_protobuf_dict(content[off:])
                    if c and len(c) >= 3:
                        return c
                    c = decode_protobuf_2(content[off:])
                    if c and len(c) >= 3:
                        return {str(k): {"data": v} for k, v in c.items()}
        return None
    except Exception:
        return None

async def major_register(release_v, access_token, open_id, name, game_version, login_url, lang_code="en"):
    field14 = bytes(ord(c) ^ KEYSTREAM[i % 32] for i, c in enumerate(open_id))
    fields = {
        1: name, 2: access_token, 3: open_id, 5: 102000007, 6: 4, 7: 1, 13: 1,
        14: field14, 15: lang_code, 16: 2, 20: game_version, 21: 1,
        22: bytes.fromhex(
            "47475245010101006d020000b260ee08e1f86b4c57f9c70f86bba26ed5d1436bcf52e142db3249d905eded757764991ca31a8373cdd26eab91b80f3f1f6f262f4f10b895d7b6937ddba30a27197453890e9da49373f736c679b8254e2f8e1623e91084a5fdd5374fe478ff99e010834553fddeb0bec4018d142e49df9bb236675b67e852f92a43586f7a7d4d0d7a197a1d4da32714dab4d069ad53214e2c33b3877420a12459738c4c619cbd815fa878bbd104776bb3e1ac7818d5397b04a666ac57f682763ff2df31bc2f846ddc7904f3dce1bda0c4b01f9698e9166f98c84f92640abe3f6317834a42e5c12573b46842c1a6ea8fe6ca9c006dca48a2087e1f983dfb5692771e4a0b15b337ad669b1d08b40862b176bace5331b49a767375b1a8469012aa70a67b55fe71b72478201d0b3ac7269c064c960361e92ee7ba8a42cc6b582bf9b965fb388fa9172ad44c4b073ac23c02080a6bcd106b691ffdf4c7cf71e42f2063fcf196e9bddc5e85be1fe5048eb1b31b460efbb46d76195eef9904c4cba326f2e17ff51fec17dd965aa06dadd4ab07d6966e4a7c38e8afd66dfde56c872bb87516a8f7313c797e4d80e5ad4a5f7afad95c1e0449254adae052e71a3fb98399f93ab30848e0d23252dd45e6fd41bc5fa7303dfb846a8fd713a0032a0b0ae96dfba1bbe41d20abd8099e2cb7fccc329d25bd153029139ef05d090a5093ea557693c0a8d491395b8a23ca844b3887dd5dfc29ac06f4b9be87883a793211b973465e2644c4f5de02b8ab01571401203fc2740423826858cc6da0194c195d27aac4ec4b9d23d506c1501d06440aca3fc180926d75d4a004d3dff21eb4ea1e8c86e6c9627248eff953e1d192d5c8efc006a7e512388ef2ebdb72ee3ad42d719f28e8f994e12ebf4c79f2ffe3abd7408ccd2236a7b89b2606247a732c10c4"
        ),
    }
    proto = _encode_proto_std(fields)
    payload = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(proto, 16))
    url = f"{login_url.rstrip('/')}/MajorRegister"
    hdrs = {
        "Accept": "*/*", "Authorization": "Bearer ",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": f"{release_v}",
        "User-Agent": "UnityPlayer/2018.4.12f1",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(url, headers=hdrs, data=payload, ssl=ssl_ctx) as resp:
                content = await resp.read()
                if resp.status != 200 or not content:
                    return None
                for off in [0, 64, 48, 32, 16]:
                    if off >= len(content):
                        continue
                    try:
                        r = decode_protobuf_2(content[off:])
                        if r and 3 in r:
                            return {str(k): {"data": v} for k, v in r.items()}
                    except Exception:
                        pass
                return None
    except Exception:
        return None

async def choose_region(region, jwt_token, login_url, release_version):
    url = f"{login_url.rstrip('/')}/ChooseRegion"
    proto = create_proto({1: region.upper()})
    payload = bytes.fromhex(encrypt_aes(proto.hex()))
    hdrs = {
        "Accept-Encoding": "gzip", "Authorization": f"Bearer {jwt_token}",
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": f"{release_version}",
        "User-Agent": "UnityPlayer/2018.4.12f1",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(url, data=payload, headers=hdrs, ssl=ssl_ctx) as r:
                return r.status
    except Exception:
        return None

def create_bio_payload(bio_text):
    if not bio_text:
        bio_text = "hello"
    if len(bio_text) > 300:
        bio_text = bio_text[:300]
    fields = {5: "", 6: "", 8: bio_text, 9: 1, 11: "", 12: "", 16: ""}
    return bytes.fromhex(encrypt_aes(create_proto(fields).hex()))

async def change_bio(jwt_token, bio_text, server_url=None):
    if not jwt_token or not bio_text:
        return False
    base = (server_url or "https://clientbp.ggpolarbear.com").rstrip("/")
    url = f"{base}/UpdateSocialBasicInfo"
    headers = {
        "Accept": "*/*", "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": "OB55",
        "User-Agent": "UnityPlayer/2018.4.12f1",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        payload = create_bio_payload(bio_text)
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(url, headers=headers, data=payload, ssl=ssl_ctx) as r:
                return r.status == 200
    except Exception:
        return False

def _get_region_from_jwt(jwt_token):
    try:
        p = jwt_token.split('.')[1]
        p += '=' * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        return (d.get('lock_region') or d.get('noti_region') or 'BD').upper()
    except Exception:
        return "BD"

def _get_region_url(region):
    region = region.upper()
    if region == "IND":
        return "https://client.ind.freefiremobile.com"
    if region in ["BR", "US", "NA"]:
        return "https://client.us.freefiremobile.com"
    return "https://clientbp.ggpolarbear.com"

async def join_clan(jwt_token, clan_id):
    if not _CLAN_PB_AVAILABLE or not clan_id:
        return False
    try:
        region = _get_region_from_jwt(jwt_token)
        base_url = _get_region_url(region)
        url = base_url.rstrip("/") + "/RequestJoinClan"
        host = base_url.replace("https://", "")
        msg = reqClan_pb2.MyMessage()
        msg.field_1 = int(clan_id)
        raw = msg.SerializeToString()
        payload = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(raw, AES.block_size))
        hdrs = {
            "Authorization": f"Bearer {jwt_token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1", "ReleaseVersion": "OB55",
            "Content-Type": "application/octet-stream",
            "Host": host, "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(url, headers=hdrs, data=payload, ssl=ssl_ctx) as r:
                return r.status == 200
    except Exception:
        return False

def _rand_suffix(n=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def _gf_field(ld, key, default=None):
    if not ld:
        return default
    v = ld.get(str(key), {})
    return v.get("data", default) if isinstance(v, dict) else (v if v is not None else default)

async def create_single_account(name_prefix, custom_bio=None, guild_id="", region="BD"):
    if not _deps_ok():
        return None
    try:
        region = (region or "BD").upper().strip()
        if region not in REGION_LANG:
            region = "BD"
        vc = await version_config(region)
        if not vc:
            return None
        release_v, remote_v, login_url, gop_1, app_version = vc
        if not login_url.endswith("/"):
            login_url += "/"
        game_version = remote_v or app_version
        lang = REGION_LANG.get(region, "en")

        bot_password = f"MAHIR_{_rand_suffix(6)}"
        uid = await register_account(bot_password, gop_1, app_version)
        if not uid:
            return None

        tok = await grant_token(uid, bot_password, gop_1, app_version)
        if not tok:
            return None
        open_id = tok["open_id"]
        access_token = tok["access_token"]
        platform = tok.get("platform", 4)

        major_payload, login_payload = await get_payload(
            access_token, open_id, platform, game_version, lang, region
        )
        nickname_final = (
            f"{name_prefix}{_rand_suffix(3)}" if name_prefix else f"MAHIR•{_rand_suffix(5)}"
        )

        mr = await major_register(
            release_v, access_token, open_id, nickname_final, game_version, login_url, lang
        )
        if not mr:
            return None

        await asyncio.sleep(3.0)

        res_json = None
        for _ in range(3):
            mp, lp = await get_payload(access_token, open_id, platform, game_version, lang, region)
            res_json = await major_login(mp, login_url, release_v)
            if res_json and (("8" in res_json) or (8 in res_json)):
                login_payload = lp
                break
            res_json = None
            await asyncio.sleep(2.0)
        if not res_json:
            return None

        def _gd(k):
            v = res_json.get(str(k))
            return v["data"] if isinstance(v, dict) and "data" in v else v

        jwt_token = _gd(8)
        server_url = _gd(10)
        acc_id_raw = _gd(1)

        if not server_url:
            if (await choose_region(region, jwt_token, login_url, release_v)) != 200:
                return None
            await asyncio.sleep(2.0)
            res_json2 = None
            for _ in range(3):
                mp2, lp2 = await get_payload(access_token, open_id, platform, game_version, lang, region)
                res_json2 = await major_login(mp2, login_url, release_v)
                if res_json2 and (("10" in res_json2) or (10 in res_json2)):
                    res_json = res_json2
                    login_payload = lp2
                    break
                res_json2 = None
                await asyncio.sleep(2.0)
            if not res_json2:
                return None
            jwt_token = _gd(8)
            server_url = _gd(10)
            acc_id_raw = _gd(1)

        bio_to_set = custom_bio if custom_bio else DEFAULT_BIO
        await asyncio.sleep(0.5)
        await change_bio(jwt_token, bio_to_set, server_url)

        if guild_id:
            await asyncio.sleep(1.0)
            await join_clan(jwt_token, guild_id)

        return {
            "account_id": acc_id_raw,
            "bot_uid": str(uid),
            "nickname": nickname_final,
            "password": bot_password,
            "jwt_token": jwt_token,
            "region": region,
        }
    except Exception as e:
        print(f"[-] Create error: {e}")
        return None

def create_account_sync(name_prefix, custom_bio=None, guild_id="", region="BD"):
    """Sync wrapper for Flask."""
    if not _deps_ok():
        print("[-] Missing deps: pip install httpx aiohttp pycryptodome protobuf-decoder google-play-scraper")
        return None
    try:
        return asyncio.run(create_single_account(name_prefix, custom_bio, guild_id, region))
    except Exception as e:
        print(f"[-] create_account_sync: {e}")
        return None
