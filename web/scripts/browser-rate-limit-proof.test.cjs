const test = require('node:test');
const assert = require('node:assert/strict');

test('a separate clone proves only the same real response and keeps the product stream intact', async () => {
  const { installBrowserRateLimitProof } = await import('./browser-rate-limit-proof.mjs');
  for (const [text, expected] of [
    ['{"error":"rate_limited","message":"safe"}', {bodyRead:'JSON',errorField:'RATE_LIMITED',messageIsString:true}],
    ['{"error":"controlled","message":"safe"}', {bodyRead:'JSON',errorField:'OTHER_OR_MISSING',messageIsString:true}],
    ['{"error":"rate_limited"}', {bodyRead:'JSON',errorField:'RATE_LIMITED',messageIsString:false}],
    ['<html>bad</html>', {bodyRead:'INVALID_JSON',errorField:'OTHER_OR_MISSING',messageIsString:false}],
  ]) {
    const url='https://test.invalid/api/argus/chart-intelligence?symbol=1321';
    let calls=0;
    const response=new Response(text,{status:429});Object.defineProperty(response,'url',{value:url});
    global.window={fetch:async()=>{calls++;return response;}};
    installBrowserRateLimitProof();
    const returned=await window.fetch(url,{headers:{Accept:'application/json'}});
    assert.equal(returned,response);assert.equal(await returned.text(),text);assert.equal(calls,1);
    assert.deepEqual(await window.__argusAcceptanceRateLimitReads.get(url),{status:429,...expected});
    assert.equal(window.__argusAcceptanceRateLimitReads.get(url+'x'),undefined);
  }
  delete global.window;
});

test('other statuses and routes are untouched, bounded proof contains no body or credentials', async () => {
  const { installBrowserRateLimitProof } = await import('./browser-rate-limit-proof.mjs');
  const url='https://test.invalid/api/argus/owner-auth/password';
  const response=new Response('{"secret":"must not collect"}',{status:429});Object.defineProperty(response,'url',{value:url});
  global.window={fetch:async()=>response};installBrowserRateLimitProof();
  assert.equal(await window.fetch(url),response);assert.equal(window.__argusAcceptanceRateLimitReads.size,0);
  delete global.window;
});
