import type { Game, GameAchievements } from './types';

/** Fixed per-record detail fields. A separate seed keeps list records unchanged. */
export interface DemoDetailFields {
  description: string | null;
  tags: string[];
  categories: string[];
  achievements: GameAchievements | null;
  rating: number | null;
  note: string;
}

const featuredDescriptions = [
  '在终年积雪的山脊上，一座废弃的天文台仍在记录星光。你将修复望远镜、整理前任观测员留下的手记，在漫长的夜里拼出一段被遗忘的航线。\n\n每一次对焦都会揭开一片新的星域，而山下小镇的灯火，也随着你的发现逐渐亮起。',
  '洪水退去后的海滨城市只剩钟楼露出水面。驾驶小船穿过被淹没的街区，打捞旧物、修补灯塔，并在潮汐涨落之间寻找家人最后的消息。',
  '一名朝圣者背着铜铃穿越赤色沙海。昼夜温差、迁徙的风暴与古老的驿站共同构成这段旅程，每一次停留都需要在补给与前进之间作出选择。',
  '月光下才会开放的花园藏着一封没有寄出的信。照料植物、修复石拱与水渠，让花园在每一个夜晚恢复一点原来的样子。',
  '阿尔卑斯山脚的木屋里堆满了无人认领的信件。作为临时邮差，你需要在雪季到来前把它们送到山间各处，也会在途中听见每封信背后的故事。',
  '城市总在下雨。作为夜班侦探，你在霓虹、积水与旧档案之间追踪一桩失踪案，线索散落在每一盏还亮着的窗口里。',
  '大地碎裂成漂浮的群岛，岛屿之间只靠风与绳桥相连。建造飞艇、规划航线，把散落在天空里的聚落重新连接起来。',
  '一头巨大的海兽在深海中缓慢游弋，它的歌声能让沉睡的珊瑚重新发光。乘坐潜航器追随它，记录那些从未见过阳光的生命。',
  '被海水淹没的大教堂里，珊瑚沿着拱顶生长成新的花窗。解开光与水流组成的机关，让教堂的钟声重新传向海面。',
  '森林会记住每一个走进来的人。跟随萤火与低语前进，你的选择将改变林中居民的命运，也改变森林本身的形状。',
  '日食只持续七分钟，而遗迹的大门只在那时开启。规划探险队伍、分配有限的火把，在一次又一次日食中揭开古文明的历法。',
  '火山城堡中的王座已空置百年。以骑士的身份穿过熔岩回廊，与守卫者交锋，决定余烬中的王国最终由谁继承。',
  '一列开往远方的夜车，每节车厢都是一个不同的季节。照看乘客、修理车厢，在抵达终点之前听完所有人的故事。',
  '极地科考站在暴风雪中失去了联系，只剩一段断续的信号。重启发电机、追踪信号来源，在冰原的寂静里找到答案。',
  '薄暮时分，一名无主的剑客走过枫叶覆盖的山道。克制而精准的剑斗，每一次出刀都需要读懂对手的呼吸。',
  '一座植物档案馆收藏着世界上已经消失的花。修复标本、培育种子，让展柜里的植物重新在温室里生长。',
  '在近地轨道上回收废弃卫星。规划燃料、拆解舱段、出售零件，并逐渐揭开一座空间站被遗弃的原因。',
  '把纸折成仙鹤，它就会带你飞向信里写到的地方。安静的解谜旅程，用折痕连接一段跨越多年的友谊。',
  '在流动的沙丘上驾驶改装赛车竞速。地形每一局都会被风重新塑造，路线与时机同样重要。',
  '风暴季节里，守灯人必须让灯塔整夜不灭。维修设备、记录航船，并在漫长的守夜中整理前任留下的日志。',
  '秋天的神社里，落叶会在某些夜晚排列成文字。帮助神社的守护者完成祭典准备，同时解读那些落叶留下的讯息。',
  '一头在星海中迁徙的鲸，背上承载着整座城市。作为城市的领航员，你需要在星云与陨石带之间为它找到方向。',
  '由齿轮驱动的城市每天都会重新排列街区。经营一家钟表店，修理居民的发条装置，在城市的节律中寻找失落的主钟。',
  '风吹过原野，一切都慢了下来。经营一座小农场、照看羊群、在季节更替中结识附近的居民，没有失败，只有日常。',
];

const tagPool = [
  '单人',
  '剧情丰富',
  '氛围',
  '手绘风格',
  '开放世界',
  '慢节奏',
  '治愈',
  '探索',
  '解谜',
  '原声出色',
  '多结局',
  '短篇',
  '高难度',
  '本地合作',
  '像素风格',
  '回合制',
  '建造',
  '叙事驱动',
];

const categoryPool = ['长篇旅程', '周末短篇', '治愈系收藏', '剧情优先', '挑战清单', '值得重玩'];

const noteSamples = [
  '第二章的音乐非常好，适合安静的晚上慢慢玩。',
  '留到假期一口气通关。记得先完成支线里的信件收集。',
  '画面很漂亮，但操作需要适应，下次从存档点 3 继续。',
  '和朋友一起玩会更有意思，等周末约人。',
];

function seededRandom(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let mixed = Math.imul(value ^ (value >>> 15), 1 | value);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(pool: readonly T[], count: number, random: () => number): T[] {
  const chosen = new Set<T>();
  while (chosen.size < Math.min(count, pool.length))
    chosen.add(pool[Math.floor(random() * pool.length)]!);
  return [...chosen];
}

function proceduralDescription(game: Game, index: number): string | null {
  if (index % 19 === 7) return null;
  const openings = [
    `《${game.title}》是一段关于离开与回归的旅程。`,
    `在《${game.title}》的世界里，地图会随着你的记忆不断改变。`,
    `《${game.title}》以安静的节奏讲述一座城市的最后一个季节。`,
  ];
  const middles = [
    '你将在零散的线索之间拼出完整的故事，每一次停留都会改变下一段路线。',
    '探索、整理与对话构成主要玩法，没有强制的时间限制。',
    '战斗并不是唯一的选择，观察与交谈往往能打开新的道路。',
  ];
  return `${openings[index % openings.length]}${middles[(index >> 2) % middles.length]}`;
}

/** Deterministic and side-effect free; called only when a detail is requested. */
export function describeDemoGame(game: Game, index: number): DemoDetailFields {
  const random = seededRandom(0x44455441 ^ Math.imul(index + 1, 0x9e3779b1));
  const tags = pick(tagPool, 3 + Math.floor(random() * 3), random);
  const categories =
    index % 9 === 5 ? [] : pick(categoryPool, 1 + Math.floor(random() * 2), random);
  const total = 18 + Math.floor(random() * 50);
  const progress =
    game.status === 'unplayed'
      ? 0
      : game.status === 'completed'
        ? 0.7 + random() * 0.3
        : 0.08 + random() * 0.55;
  // Featured sample 潮汐之后 and every seventh record deliberately have no data.
  const achievements =
    index === 1 || index % 7 === 3 ? null : { unlocked: Math.round(total * progress), total };
  // Featured sample 赤沙行者 deliberately has neither rating nor note.
  const rated = index === 0 || (index !== 2 && game.status !== 'unplayed' && random() > 0.45);
  const rating = rated ? 3 + Math.floor(random() * 3) : null;
  const note =
    index === 0 ? noteSamples[0]! : index !== 2 && random() > 0.7 ? noteSamples[index % 4]! : '';
  return {
    description: featuredDescriptions[index] ?? proceduralDescription(game, index),
    tags,
    categories,
    achievements,
    rating,
    note,
  };
}
