"""Safe image diagnostics without credentials, request URLs or raw SDK messages."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageFailure:
    kind: str
    stage: str = 'request'
    status: int | None = None

    def message(self, provider: str) -> str:
        context = {'upload': '上传参考图时', 'download': '下载生成图片时'}.get(self.stage, '请求生图时')
        reasons = {
            'tls': (f'{context}安全连接中断（TLS/SSL）', '请检查后台网络或代理配置后手动重试'),
            'certificate': (f'{context}证书校验失败', '请检查系统时间、证书及代理配置后手动重试'),
            'timeout': (f'{context}连接超时', '请检查后台网络，稍后手动重试'),
            'network': (f'{context}无法连接服务商', '请检查后台网络、接口地址或代理配置后手动重试'),
            'auth': ('API Key 无效或已失效', '请在右上角“模型与 API”中检查并保存此服务商的密钥'),
            'permission': ('当前账号没有模型访问权限', '请在服务商控制台确认模型已开通及密钥权限'),
            'quota': ('账户余额或可用配额不足', '请在服务商控制台检查余额及配额后手动重试'),
            'rate_limit': ('请求触发限流', '请稍后手动重试，避免连续重复提交'),
            'model': ('模型不存在或当前接口不支持此模型', '请在“模型与 API”中核对模型与接口地域'),
            'content': ('请求被服务商内容审核拒绝', '请检查画面描述和参考图后手动重试'),
            'invalid_request': ('服务商未接受请求参数或参考图', '请检查图片格式、尺寸及模型设置'),
            'server': ('服务商暂时异常', '请稍后查看服务商任务状态并手动重试'),
            'download': ('服务商已返回图片，但未能下载到本机', '请检查后台网络及图片下载地址后手动重试'),
            'parse': ('图片响应格式无法解析', '请核对所选模型及服务商任务记录后手动重试'),
            'empty': ('响应中未包含可用图片', '请核对所选模型及服务商任务记录后手动重试'),
            'unknown': ('生图请求异常，未取得可识别的失败原因', '请查看服务商任务记录或后台日志后手动重试'),
        }
        reason, action = reasons.get(self.kind, reasons['unknown'])
        status = f'（HTTP {self.status}）' if self.status else ''
        return f'{provider}：{reason}{status}。{action}；已有图片和文字已保留。'


def response_failure(status, code='', stage='request'):
    status = status if type(status) is int and 100 <= status <= 599 else None
    code = str(code or '').lower()
    if any(part in code for part in ('arrearage', 'insufficient', 'quota', 'balance')):
        kind = 'quota'
    elif any(part in code for part in ('datainspection', 'contentfilter', 'content_filter', 'contentpolicy', 'safety')):
        kind = 'content'
    elif status == 401 or any(part in code for part in ('invalidapikey', 'invalid_api_key', 'authentication')):
        kind = 'auth'
    elif status == 429 or any(part in code for part in ('throttl', 'ratelimit', 'rate_limit')):
        kind = 'rate_limit'
    elif status == 403:
        kind = 'permission'
    elif status == 402:
        kind = 'quota'
    elif status == 404 or 'modelnotfound' in code:
        kind = 'model'
    elif status is not None and status >= 500:
        kind = 'server'
    else:
        kind = 'invalid_request'
    return ImageFailure(kind, stage, status)


def exception_failure(exc, stage='request'):
    chain = []
    while exc is not None and len(chain) < 8 and all(exc is not item for item in chain):
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    for item in chain:
        status = getattr(item, 'status_code', None) or getattr(getattr(item, 'response', None), 'status_code', None)
        if type(status) is int:
            return response_failure(status, getattr(item, 'code', ''), stage)
    # Inspect exception text only for classification; never include it in public diagnostics.
    detail = ' '.join(str(item)[:4000] for item in chain).lower()
    types = ' '.join(type(item).__name__.lower() for item in chain)
    if stage == 'request' and ('/uploads' in detail or 'getpolicy' in detail):
        stage = 'upload'
    if 'certificate_verify_failed' in detail or 'certificate verify failed' in detail:
        kind = 'certificate'
    elif 'ssl' in types or 'tls' in types or 'ssl:' in detail or 'unexpected_eof_while_reading' in detail:
        kind = 'tls'
    elif 'timeout' in types or 'timed out' in detail:
        kind = 'timeout'
    elif any(part in types for part in ('connection', 'connecterror', 'proxyerror', 'gaierror')):
        kind = 'network'
    else:
        kind = 'download' if stage == 'download' else 'unknown'
    return ImageFailure(kind, stage)
