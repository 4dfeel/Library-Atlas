import type { DownloadTask, ExtractTask } from '@/lib/data';
import { formatBytes } from '@/lib/utils';

export const stateLabels: Record<DownloadTask['state'], string> = {
  queued: '排队中',
  resolving: '正在获取下载地址',
  downloading: '下载中',
  verifying: '校验中',
  paused: '已暂停',
  done: '已下载',
  failed: '下载失败',
  cancelled: '已取消',
  reauth_required: '需要重新登录',
  interrupted: '已中断',
};

export const extractLabels: Record<ExtractTask['state'], string> = {
  queued: '等待解压',
  checking: '正在核对文件',
  extracting: '解压中',
  committing: '正在完成',
  done: '已解压',
  not_needed: '不需要解压',
  failed: '解压失败',
  cancelled: '已取消解压',
  interrupted: '解压已中断',
};

export function messageOf(error: unknown) {
  return error instanceof Error ? error.message : '操作没有完成，请重试。';
}

export function amount(done: number, total: number | null) {
  return total === null
    ? `已下载 ${formatBytes(done)} · 总大小未知`
    : `${formatBytes(done)} / ${formatBytes(total)}`;
}
