// 从清华镜像下载 cp313 win_amd64 wheel（pypi.org 直连不通），绕开 pip 的解包权限问题
import { writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const OUT = 'C:\\Users\\13047\\DSwork\\toys\\pet\\.wheels';
const MIRRORS = [
  'https://pypi.tuna.tsinghua.edu.cn',
  'https://mirrors.aliyun.com/pypi',
];
const PKGS = ['pillow', 'numpy'];

const get = async (url, ms = 45000) => {
  const res = await fetch(url, {
    headers: { 'User-Agent': 'dsh-pet-setup' },
    signal: AbortSignal.timeout(ms),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return res;
};

await mkdir(OUT, { recursive: true });

for (const name of PKGS) {
  let ok = false;
  for (const base of MIRRORS) {
    try {
      console.log(`-- ${name}: trying ${base}`);
      const res = await get(`${base}/pypi/${name}/json`);
      const meta = await res.json();
      const ver = meta.info.version;
      const files = meta.releases[ver] || [];
      const pick = files.find((f) => /cp313.*win_amd64\.whl$/.test(f.filename));
      if (!pick) {
        console.log(`   no cp313 win_amd64 wheel for ${name} ${ver}; sample: ${files.map(f => f.filename).slice(0, 8).join(', ')}`);
        continue;
      }
      const url = pick.url.startsWith('http') ? pick.url : base + pick.url;
      console.log(`   ${name} ${ver} -> ${pick.filename} (${(pick.size / 1048576).toFixed(1)} MB)`);
      const dl = await get(url, 120000);
      const buf = Buffer.from(await dl.arrayBuffer());
      const dest = join(OUT, pick.filename);
      await writeFile(dest, buf);
      console.log(`   saved ${pick.filename} (${(buf.length / 1048576).toFixed(1)} MB)`);
      ok = true;
      break;
    } catch (e) {
      console.log(`   FAILED: ${e.message}`);
    }
  }
  if (!ok) console.log(`!! ${name} 全部镜像失败`);
}
console.log('done');
