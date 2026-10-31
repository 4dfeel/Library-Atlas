import type { Game } from './types';

const palettes = [
  ['#142A39', '#659CAB', '#C0DBCE'],
  ['#302C3E', '#9B7699', '#E5C4B7'],
  ['#382823', '#B97C4D', '#F0C98E'],
  ['#182D2C', '#578778', '#B0C3A0'],
  ['#252C47', '#626E9C', '#C9B9CB'],
  ['#33222A', '#AF6970', '#F0C7A8'],
] as const;

function xmlText(value: string): string {
  const printable = Array.from(value)
    .filter((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code >= 32 || code === 9 || code === 10 || code === 13;
    })
    .join('');
  return printable.replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character] ??
      character,
  );
}

function coverTitleLines(title: string): string[] {
  const lines: string[] = [];
  let line = '';
  let units = 0;
  for (const character of Array.from(title)) {
    const width = /[\u0020-\u007E]/.test(character) ? 0.55 : 1;
    if (units + width > 15) {
      lines.push(line);
      if (lines.length === 2) return [lines[0]!, `${lines[1]!.slice(0, -1)}…`];
      line = '';
      units = 0;
    }
    line += character;
    units += width;
  }
  if (line) lines.push(line);
  return lines;
}

/** Wide local backdrop for detail pages; null when absent or not ordinary. */
export function getBackdropSource(game: Game): string | null {
  if (game.visibility !== 'normal' || !game.background) return null;
  return game.background.startsWith('/demo/backdrops/') ? game.background : null;
}

/** Called by mounted cards only; no eager creation or request for 5000 covers. */
export function getCoverSource(game: Game): string | null {
  if (game.visibility !== 'normal' || game.cover.kind === 'missing') return null;
  if (game.cover.kind === 'remote') return game.cover.url ?? null;
  if (game.cover.kind === 'art')
    return `/demo/covers/cover-${String(game.cover.index).padStart(2, '0')}.svg`;
  const index = game.cover.index;
  // Offset by index/18 so works of one kind (a fixed index stride) still vary.
  const [dark, mid, light] =
    palettes[(index + Math.floor(index / 18)) % palettes.length] ?? palettes[0];
  const horizon = 340 + (index % 7) * 25;
  const moonX = 100 + (index % 5) * 88;
  const title = coverTitleLines(game.title)
    .map((line, row) => `<tspan x="40" y="${754 + row * 44}">${xmlText(line)}</tspan>`)
    .join('');
  const subtitle = xmlText(Array.from(game.subtitle).slice(0, 42).join(''));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" viewBox="0 0 600 900"><defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="${dark}"/><stop offset="1" stop-color="${mid}"/></linearGradient><linearGradient id="shade" x2="0" y2="1"><stop stop-color="${dark}" stop-opacity="0"/><stop offset="1" stop-color="${dark}"/></linearGradient></defs><rect width="600" height="900" fill="url(#sky)"/><circle cx="${moonX}" cy="245" r="72" fill="${light}" opacity=".65"/><path d="M0 ${horizon + 130} 140 ${horizon - 20} 240 ${horizon + 80} 430 ${horizon - 100} 600 ${horizon + 80}V900H0Z" fill="${mid}"/><path d="M0 ${horizon + 240} 180 ${horizon + 80} 350 ${horizon + 170} 600 ${horizon + 30}V900H0Z" fill="${dark}" opacity=".8"/><path d="M${100 + (index % 70)} 900 Q280 650 420 ${horizon + 170}" fill="none" stroke="${light}" opacity=".3" stroke-width="3"/><rect width="600" height="900" fill="url(#shade)"/><text x="40" y="70" fill="${light}" font-size="12" letter-spacing="5" font-family="sans-serif">ATLAS STUDIES / ${String(index + 1).padStart(4, '0')}</text><text fill="${light}" font-size="32" font-family="'Segoe UI','Microsoft YaHei',sans-serif">${title}</text><path d="M40 825H560" stroke="${light}" stroke-opacity=".4"/><text x="40" y="852" fill="${light}" font-size="10" letter-spacing="1.5" font-family="sans-serif">${subtitle}</text><text x="40" y="876" fill="${light}" opacity=".6" font-size="9" letter-spacing="3" font-family="sans-serif">PROCEDURAL EDITION</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
