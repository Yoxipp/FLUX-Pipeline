const {test}=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs'),ts=require('typescript')
const source=fs.readFileSync('app/src/lib/activityNotify.ts','utf8')
const mod={exports:{}}
new Function('exports','module',ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(mod.exports,mod)
const {actionToType,notificationReason}=mod.exports
const off={notifyFollowed:false,notifyPublish:false,notifyComment:false,notifyError:false}
const ctx=(prefs,extra={})=>({prefs:{...off,...prefs},followed:false,username:'MILO',project:'UTAH',...extra})
const ev=(action,user='ADAM',project='UTAH')=>({action,user,project})

test('categories follow the Activity page filters',()=>{
 assert.equal(actionToType('publish'),'publish')
 assert.equal(actionToType('export_failed'),'publish')
 assert.equal(actionToType('comment'),'comment')
 assert.equal(actionToType('publish error'),'publish')
 assert.equal(actionToType('error'),'error')
 assert.equal(actionToType('install'),'update')
})
test('followed tasks keep notifying by default, whoever the author',()=>{
 assert.equal(notificationReason(ev('publish','MILO'),ctx({notifyFollowed:true},{followed:true})),'followed')
 assert.equal(notificationReason(ev('publish'),ctx({},{followed:true})),null)
})
test('project categories: other artists, active project only',()=>{
 const prefs={notifyPublish:true,notifyComment:true,notifyError:true}
 assert.equal(notificationReason(ev('publish'),ctx(prefs)),'publish')
 assert.equal(notificationReason(ev('comment'),ctx(prefs)),'comment')
 assert.equal(notificationReason(ev('error'),ctx(prefs)),'error')
 assert.equal(notificationReason(ev('publish','milo'),ctx(prefs)),null)
 assert.equal(notificationReason(ev('publish','ADAM','OTHER'),ctx(prefs)),null)
 assert.equal(notificationReason({action:'publish',user:'A'},ctx(prefs)),null)
 assert.equal(notificationReason(ev('import'),ctx(prefs)),null)
 assert.equal(notificationReason(ev('publish'),ctx({notifyComment:true})),null)
})
