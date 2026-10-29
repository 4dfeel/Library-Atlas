import type { DemoSize, Game, GameStatus, Visibility } from './types';

const featured = [
  ['星穹观测站', 'ASTRAL OBSERVATORY', '探索'],
  ['潮汐之后', 'AFTER THE TIDE', '冒险'],
  ['赤沙行者', 'RED SAND PILGRIM', '角色扮演'],
  ['月下花园', 'THE MOON GARDEN', '休闲'],
  ['山间来信', 'LETTERS FROM THE ALPS', '模拟'],
  ['雨幕之外', 'BEYOND THE RAIN', '解谜'],
  ['浮岛纪元', 'AGE OF FLOATING ISLES', '冒险'],
  ['深海回声', 'ECHOES OF THE DEEP', '探索'],
  ['珊瑚圣殿', 'CORAL CATHEDRAL', '解谜'],
  ['森林的低语', 'WHISPERS OF THE WOODS', '角色扮演'],
  ['日曜遗迹', 'SOLAR RELICS', '策略'],
  ['余烬王座', 'THRONE OF EMBERS', '动作'],
  ['远方列车', 'THE DISTANT TRAIN', '模拟'],
  ['极地信号', 'POLAR SIGNAL', '探索'],
  ['薄暮之刃', 'TWILIGHT BLADE', '动作'],
  ['植物档案馆', 'BOTANICAL ARCHIVE', '休闲'],
  ['轨道拾荒者', 'ORBITAL SALVAGE', '策略'],
  ['折纸之旅', 'PAPER CRANES', '解谜'],
  ['沙丘疾行', 'DUNE RUNNER', '竞速'],
  ['守灯人', 'THE LIGHTHOUSE KEEPER', '冒险'],
  ['秋日神社', 'AUTUMN SHRINE', '休闲'],
  ['星海鲸歌', 'SONG OF THE COSMIC WHALE', '探索'],
  ['发条之城', 'CLOCKWORK CITY', '策略'],
  ['风中的原野', 'MEADOW IN THE WIND', '模拟'],
] as const;

const words = [
  '失落航线',
  '琥珀之境',
  '夜航日记',
  '漫游者',
  '晨雾回廊',
  '银河边界',
  '旧城往事',
  '天空档案',
  '银色旅途',
  '远山回响',
];
const qualifiers = [
  '终章',
  '序曲',
  '新世界',
  '永恒回声',
  '漫长的归途',
  '重逢',
  '未知领域',
  'The Last Horizon',
  'Beyond the Stars',
  '遠い空の向こう',
];
const genres = [
  '探索',
  '冒险',
  '角色扮演',
  '休闲',
  '模拟',
  '解谜',
  '策略',
  '动作',
  '竞速',
] as const;
const statuses: readonly GameStatus[] = ['unplayed', 'playing', 'completed', 'paused'];

function seededRandom(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let mixed = Math.imul(value ^ (value >>> 15), 1 | value);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

function visibilityFor(index: number): Visibility {
  if (index < 24) return 'normal';
  if (index % 97 === 0) return 'private';
  if (index % 113 === 0) return 'hidden';
  if (index % 151 === 0) return 'quarantined';
  return 'normal';
}

/** Local synthetic fixtures only. No identifier refers to a Steam app or user. */
export function generateDemoGames(size: DemoSize): readonly Game[] {
  const random = seededRandom(0x41544c41);
  return Array.from({ length: size }, (_, index): Game => {
    const entry = featured[index];
    const visibility = visibilityFor(index);
    const status = statuses[Math.floor(random() * statuses.length)] ?? 'unplayed';
    let title: string =
      entry?.[0] ??
      `${words[index % words.length]}：${qualifiers[index % qualifiers.length]} ${String(index + 1).padStart(4, '0')}`;
    if (index === 28)
      title =
        '跨越星海的最后一封信：遠い銀河の向こうへ — A Journey Beyond the Infinite Horizon · 完整典藏纪念版';
    if (index === 29)
      title = 'TheLastObservatoryBeyondTheEndOfTheKnownUniverseCollectorsEditionWithoutAnySpaces';
    if (visibility !== 'normal') title = `PRIVATE_SENTINEL_${visibility.toUpperCase()}_${index}`;
    const playtimeMinutes = status === 'unplayed' ? 0 : Math.round(30 + random() * 14_000);
    return {
      id: `demo-${String(index + 1).padStart(5, '0')}`,
      title,
      subtitle: entry?.[1] ?? `ATLAS ORIGINALS · VOL. ${String(index + 1).padStart(4, '0')}`,
      genre: entry?.[2] ?? genres[index % genres.length] ?? '探索',
      status,
      installed: index < 7 || random() > 0.66,
      playtimeMinutes: index % 173 === 0 && index > 24 ? null : playtimeMinutes,
      favorite: index === 0 || index === 3 || index === 7 || random() > 0.84,
      visibility,
      cover: {
        kind: index < 24 ? 'art' : index % 11 === 2 ? 'missing' : 'procedural',
        index: index < 24 ? index + 1 : index,
      },
      background:
        index % 5 === 4
          ? null
          : `/demo/covers/cover-${String((index % 24) + 1).padStart(2, '0')}.svg`,
      addedAt: new Date(Date.UTC(2026, 9, 30) - index * 86_400_000).toISOString(),
      lastPlayedAt:
        status === 'unplayed'
          ? null
          : new Date(Date.UTC(2026, 9, 30) - (index % 60) * 86_400_000).toISOString(),
    };
  });
}
