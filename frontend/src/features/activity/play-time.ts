/** As Steam says it: minutes while it is short, hours with a decimal after that. */
export function formatPlayTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) return '不足 1 分钟';
  if (minutes < 60) return `${minutes} 分钟`;
  return `${(minutes / 60).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 小时`;
}
