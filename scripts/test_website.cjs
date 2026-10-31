const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

test('the homepage loads one static curated snapshot and makes no per-person feed calls', async () => {
  const html = readFileSync(new URL('../index.html', 'file://' + __filename), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const requests = [];
  const nodes = [];
  const element = tag => {
    const node = {tag, children: [], setAttribute() {}, addEventListener() {},
      append(...children) {this.children.push(...children);},
      replaceChildren(...children) {this.children = children;}};
    nodes.push(node); return node;
  };
  const grid = element('grid');
  await vm.runInNewContext(script, {
    document: {getElementById: () => grid, createElement: element}, console,
    fetch: async url => {
      requests.push(url);
      return {ok: true, json: async () => ({version: 1, personalities: [{
        id: 'ada', name: 'Ada', artwork_url: '/data/v1/personalities/art/ada.png?v=abc',
        feed_url: '/data/v1/personalities/ada.json',
        episodes: [{title: 'Approved interview', podcast_title: 'Interviews', language: 'en',
          pub_date: '2026-10-31', episode_url: 'https://podcast.test/episode'}],
      }]})};
    },
  });
  assert.deepEqual(requests, ['/website-data/personalities.json']);
  assert.equal(grid.children.length, 1);
  assert.ok(nodes.some(node => node.textContent === 'Approved interview'));
  assert.ok(nodes.some(node => node.tag === 'img' && node.src === '/data/v1/personalities/art/ada.png?v=abc'));
});

test('the published website snapshot contains only public card fields', () => {
  const snapshot = JSON.parse(readFileSync(new URL('../website-data/personalities.json', 'file://' + __filename), 'utf8'));
  assert.equal(snapshot.version, 1);
  assert.ok(Number.isFinite(Date.parse(snapshot.updatedAt)));
  for (const person of snapshot.personalities) {
    assert.deepEqual(Object.keys(person).sort(), ['artwork_url', 'episodes', 'id', 'name', 'title']);
    assert.ok(person.episodes.length <= 2);
    for (const episode of person.episodes) {
      assert.deepEqual(Object.keys(episode).sort(), ['audio_url', 'episode_url', 'language', 'podcast_artwork_url', 'podcast_title', 'pub_date', 'title']);
      assert.match(episode.language, /^en(?:[-_]|$)/i);
    }
  }
});
