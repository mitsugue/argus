const assert=require('node:assert/strict'),vm=require('node:vm'),path=require('node:path');
const {buildSync}=require('esbuild');
const entry=path.resolve('src/lib/ownerSession.ts');
const code=buildSync({entryPoints:[entry],bundle:true,write:false,platform:'node',format:'cjs',
 define:{'import.meta.env':JSON.stringify({VITE_ARGUS_OWNER_AUTH_REQUIRED:'1',VITE_ARGUS_BACKEND_URL:'https://resume-api.test'})},logLevel:'silent'}).outputFiles[0].text;
const store=new Map(),flags=new Map(),calls=[],bearer='f'.repeat(43),expiry=Date.now()+86400000;
let cookie='',writeFailure=false,online=true,standalone=true,mode='ok';
const storage={getItem:k=>store.get(k)??null,setItem:(k,v)=>{if(writeFailure&&k==='argus.owner.session.v1')throw new DOMException('fixture','QuotaExceededError');store.set(k,v);},removeItem:k=>store.delete(k)};
const fetcher=async(input,init)=>{
 const r=new Request(input,init);calls.push(r);const echo={'X-ARGUS-OWNER-NONCE':r.headers.get('X-ARGUS-OWNER-NONCE')??''};
 if(r.url.endsWith('/password'))return Response.json({token:bearer,expiresAt:expiry});
 if(r.url.endsWith('/logout')){if(mode==='network')throw new TypeError('fixture');cookie='';return Response.json({loggedOut:true},{headers:echo});}
 if(r.method==='POST'){
  assert.equal(r.credentials,'include');assert.deepEqual(await r.json(),{resume:true});
  if(!cookie)return Response.json({},{status:401});
  if(mode==='noecho')return Response.json({token:bearer,expiresAt:expiry});
  if(mode==='invalid')return Response.json({token:bearer,expiresAt:Date.now()+864000000},{headers:echo});
  return Response.json({token:cookie,expiresAt:expiry},{headers:echo});
 }
 if(r.headers.get('X-ARGUS-OWNER-RESUME')==='1'){
  assert.equal(r.credentials,'include');cookie=bearer;
 }else assert.equal(r.credentials,'omit','ordinary browser must not participate in cookie recovery');
 return Response.json({authenticated:true},{headers:echo});
};
function documentSession(){
 const exports={},module={exports};const timers=[];
 const ctx={exports,module,URL,Request,Response,Headers,DOMException,AbortController,AbortSignal,Date,Error,
  crypto:require('node:crypto').webcrypto,sessionStorage:storage,
  localStorage:{getItem:k=>flags.get(k)??null,setItem:(k,v)=>flags.set(k,v),removeItem:k=>flags.delete(k)},
  navigator:{get onLine(){return online;},get standalone(){return standalone;}},
  document:{hidden:false,visibilityState:'visible',documentElement:{dataset:{}},addEventListener(){},removeEventListener(){}},
  window:{location:{origin:'https://resume-ui.test'},matchMedia:()=>({matches:standalone}),fetch:fetcher,setInterval:()=>1,clearInterval(){},addEventListener(){}},
  fetch:fetcher,setTimeout:(fn,ms)=>{timers.push({fn,ms});if(ms<=10000)queueMicrotask(fn);return timers.length;},clearTimeout(){}};
 vm.runInNewContext(code,ctx);return {api:module.exports,ctx};
}
(async()=>{
 const initial=documentSession();writeFailure=true;await initial.api.passwordLogin('fixture');
 assert.equal(initial.ctx.document.documentElement.dataset.argusOwnerSessionStore,'quota');
 assert(initial.api.hasOwnerSession());assert(!store.has('argus.owner.session.v1'));assert(cookie);
 const recovered=documentSession();const before=calls.length;
 const flight=recovered.api.restoreOwnerSession();assert.equal(recovered.api.restoreOwnerSession(),flight);
 assert(await flight);assert.equal(calls.length,before+2);assert(recovered.api.hasOwnerSession());
 assert(calls.slice(before).every(r=>r.url.endsWith('/owner-auth/session')),'no market read or login issuance');
 const retained=calls.length;for(let i=0;i<10;i++)assert(await recovered.api.restoreOwnerSession());
 assert.equal(calls.length,retained,'an active session returns without network');
 writeFailure=false;store.clear();mode='network';await assert.rejects(recovered.api.logoutOwner());
 assert.equal(flags.get('argus.owner.logged-out.v1'),'1');
 store.clear();const afterLogout=documentSession();const beforeBlocked=calls.length;
 assert.equal(await afterLogout.api.restoreOwnerSession(),false);assert.equal(calls.length,beforeBlocked,
  'offline explicit logout remains blocked even after sessionStorage loss');
 mode='ok';const reauthorized=documentSession();await reauthorized.api.passwordLogin('fixture');assert.equal(flags.size,0);
 store.clear();mode='invalid';const invalid=documentSession();assert.equal(await invalid.api.restoreOwnerSession(),false);
 assert.equal(invalid.api.hasOwnerSession(),false);assert.equal(invalid.api.hasSavedOwnerSession(),false);
 store.clear();flags.clear();mode='ok';standalone=false;const tab=documentSession();const beforeTab=calls.length;
 assert.equal(await tab.api.restoreOwnerSession(),false);assert.equal(calls.length,beforeTab);
 await tab.api.passwordLogin('fixture');assert(!store.has('argus.owner.session.v1'));
 assert(!JSON.stringify([...flags.values()]).includes(bearer),'no bearer in durable JS storage');
 console.log('PASS missing/blocked sessionStorage, scoped cookie restore, single flight, original expiry, no market read, ordinary return zero requests, offline logout and browser isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
