// Optional development verification only. No browser dependency is shipped.
// npm install --prefix /private/tmp/omneum-provenance-ui-check --ignore-scripts playwright-core@1.56.1
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || '/private/tmp/omneum-provenance-ui-check/node_modules/playwright-core/index.mjs');
const output = '/private/tmp/omneum-provenance-ui-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8765');
  await page.waitForFunction(() => document.getElementById('counts').textContent.includes('36 sources'));
  const model = await page.evaluate(() => ({
    nodes: cy.nodes().length, edges: cy.edges().length,
    sources: cy.nodes('[category="source"]').length,
    claims: cy.nodes('[category="claim"]').length,
    visibleNodes: cy.nodes(':visible').length,
    visibleEdges: cy.edges(':visible').length,
    sourceColor: cy.nodes('[category="source"]').first().style('background-color'),
    claimColor: cy.nodes('[category="claim"]').first().style('background-color'),
    sourceShape: cy.nodes('[format="JSON"]').first().style('shape'),
    claimShape: cy.nodes('[category="claim"]').first().style('shape'),
    arrow: cy.edges('[type="upstream"]').first().style('target-arrow-shape'),
    citationStyle: cy.edges('[type="citation"]').first().style('line-style'),
  }));
  assert.deepEqual([model.nodes, model.edges, model.sources, model.claims], [48, 112, 36, 12]);
  assert.deepEqual([model.visibleNodes, model.visibleEdges], [36, 40]);
  assert.equal(await page.locator('#layout').inputValue(), 'lineage');
  assert.equal(await page.locator('#assertions').isChecked(), false);
  assert.notEqual(model.sourceColor, model.claimColor);
  assert.equal(model.sourceShape, 'round-rectangle');
  assert.equal(model.claimShape, 'diamond');
  assert.equal(model.arrow, 'triangle');
  assert.equal(model.citationStyle, 'dashed');
  async function clickElement(id, edge = false) {
    const position = await page.evaluate(({ id, edge }) => {
      const element = cy.getElementById(id);
      const p = edge ? element.renderedMidpoint() : element.renderedPosition();
      const bounds = document.getElementById('graph').getBoundingClientRect();
      return { x: bounds.x + p.x, y: bounds.y + p.y };
    }, { id, edge });
    await page.mouse.click(position.x, position.y);
  }
  const sourceId = await page.evaluate(() => cy.nodes().filter(n => n.data('display_metadata').key === 'ind-web').id());
  await clickElement(sourceId);
  assert.equal(JSON.parse(await page.locator('#stored-json').textContent()).id, sourceId);
  await page.locator('#assertions').check();
  await page.waitForFunction(() => cy.nodes(':visible').length === 48 && cy.edges(':visible').length === 112);
  const claimId = await page.evaluate(() => cy.nodes('[category="claim"]').first().id());
  await clickElement(claimId);
  assert.equal(JSON.parse(await page.locator('#stored-json').textContent()).id, claimId);
  await page.locator('#assertions').uncheck();
  await page.waitForFunction(() => cy.edges('[type="assertion"]').every(e => e.style('display') === 'none'));
  assert.equal(await page.evaluate(() => cy.nodes(':visible').length), 36);
  assert.equal(await page.evaluate(() => cy.edges('[type="assertion"]:visible').length), 0);
  await page.locator('#chain').click();
  const chainEdges = await page.evaluate(() => cy.edges().filter(e => e.source().data('display_metadata').key === 'gateway'
    && e.target().data('display_metadata').key === 'registry').map(e => ({ id: e.id(), type: e.data('type'), stored: e.data('stored_relationship') })));
  assert.equal(chainEdges.length, 2);
  for (const edge of chainEdges) {
    await clickElement(edge.id, true);
    const json = JSON.parse(await page.locator('#relationship-json').textContent());
    assert.deepEqual(json, edge.stored);
    assert.equal(json.type, edge.type);
    const derived = JSON.parse(await page.locator('#derived-json').textContent());
    assert.equal(derived.direction, edge.type === 'upstream' ? 'downstream → upstream' : 'citing → cited');
  }
  const derivation = chainEdges.find(e => e.type === 'upstream');
  await clickElement(derivation.id, true);
  await page.screenshot({ path: `${output}/selected-chain.png` });
  await page.locator('#layout').selectOption('preset');
  await page.locator('#assertions').check();
  await page.locator('#fit').click();
  await clickElement(derivation.id, true);
  await page.screenshot({ path: `${output}/selected-provenance.png` });
  await page.locator('#demo').click();
  await page.waitForFunction(() => cy.nodes(':visible').length === 36 && document.getElementById('relationship-json') !== null);
  assert.equal(await page.locator('#assertions').isChecked(), false);
  assert.deepEqual(JSON.parse(await page.locator('#relationship-json').textContent()), derivation.stored);
  const screenshotState = await page.evaluate(() => {
    const visible = cy.nodes(':visible');
    const intersections=[];
    for(let i=0;i<visible.length;i++) for(let j=i+1;j<visible.length;j++) {
      const a=visible[i].renderedBoundingBox(),b=visible[j].renderedBoundingBox();
      if(a.x1<b.x2 && a.x2>b.x1 && a.y1<b.y2 && a.y2>b.y1) intersections.push([visible[i].id(),visible[j].id()]);
    }
    return {intersections,zoom:cy.zoom(), renderedLabelSize:17*cy.zoom()};
  });
  assert.deepEqual(screenshotState.intersections, []);
  assert.ok(screenshotState.renderedLabelSize >= 12);
  await page.screenshot({ path: `${output}/research-1440.png` });
  await page.locator('#citations').uncheck();
  await page.waitForFunction(() => cy.edges('[type="citation"]:visible').length === 0);
  assert.equal(await page.evaluate(() => cy.edges('[type="upstream"]:visible').length), 27);
  await page.locator('#citations').check();
  await page.locator('#dependents').check();
  assert.equal(await page.evaluate(() => cy.nodes(':visible').length), 36);
  await page.locator('#dependents').uncheck();
  await page.locator('#clear').click();
  await page.locator('#assertions').check();
  const oldZoom = await page.evaluate(() => cy.zoom());
  await page.locator('#zoom-in').click();
  assert.ok(await page.evaluate(() => cy.zoom()) > oldZoom);
  await page.locator('#zoom-out').click();
  const canvas = await page.locator('#graph').boundingBox();
  const beforePan = await page.evaluate(() => cy.pan());
  await page.mouse.move(canvas.x+15,canvas.y+15);
  await page.mouse.down();
  await page.mouse.move(canvas.x+70,canvas.y+45,{steps:8});
  await page.mouse.up();
  assert.notDeepEqual(await page.evaluate(() => cy.pan()),beforePan);
  const dragPosition = await page.evaluate(id => {
    const p=cy.getElementById(id).renderedPosition();
    const r=document.getElementById('graph').getBoundingClientRect();
    return {x:r.x+p.x,y:r.y+p.y};
  },sourceId);
  const beforePosition=await page.evaluate(id=>cy.getElementById(id).position(),sourceId);
  await page.mouse.move(dragPosition.x,dragPosition.y);
  await page.mouse.down();
  await page.mouse.move(dragPosition.x+40,dragPosition.y+25,{steps:8});
  await page.mouse.up();
  assert.notDeepEqual(await page.evaluate(id=>cy.getElementById(id).position(),sourceId),beforePosition);
  await page.locator('#layout').selectOption('cose');
  await page.waitForFunction(() => !cy.nodes().some(n => n.animated()));
  assert.equal(await page.evaluate(() => cy.nodes().length), 48);
  await page.locator('#layout').selectOption('preset');
  await page.locator('#reload').click();
  await page.waitForFunction(() => document.getElementById('status').textContent.includes('AGE assertions verified (72)'));
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'passed', ...model, screenshotState,
    screenshots: [`${output}/research-1440.png`, `${output}/selected-chain.png`, `${output}/selected-provenance.png`] }, null, 2));
} finally {
  await browser.close();
}
