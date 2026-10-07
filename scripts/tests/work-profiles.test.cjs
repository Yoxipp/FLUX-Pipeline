const {test}=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs'),ts=require('typescript')
const source=fs.readFileSync('app/src/lib/workProfiles.ts','utf8')
const mod={exports:{}}
new Function('exports','module',ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(mod.exports,mod)
const W=mod.exports

test('first load keeps the old per-browser Folder Manager values',()=>{
 const u=W.readUserWorkProfile(undefined,{folderTileSize:'lg',folderLayout:'quad'})
 assert.deepEqual(u.active,W.DEFAULT_REF)
 assert.equal(u.prefs.folderTileSize,'lg')
 assert.equal(u.prefs.folderLayout,'quad')
 assert.equal(u.prefs.launcher,'compact')
 assert.deepEqual(u.custom,[])
})
test('saved prefs win over legacy values and corrupt data falls back to defaults',()=>{
 const u=W.readUserWorkProfile({active:{source:'user',id:'me'},prefs:{folderTileSize:'sm',launcher:'huge',startPage:'/nowhere'},custom:[{id:'me',name:'Moi',prefs:{launcher:'full'}},{id:'me',name:'dup'},{name:'no id'}]},{folderTileSize:'lg'})
 assert.deepEqual(u.active,{source:'user',id:'me'})
 assert.equal(u.prefs.folderTileSize,'sm')
 assert.equal(u.prefs.launcher,'compact')
 assert.equal(u.prefs.startPage,'/')
 assert.deepEqual(u.custom,[{id:'me',name:'Moi',prefs:{launcher:'full'}}])
 assert.deepEqual(W.readUserWorkProfile('garbage').active,W.DEFAULT_REF)
})
test('applying a profile then tweaking shows exactly the modified keys',()=>{
 const anim=W.findProfile({source:'builtin',id:'animation'},[],[])
 const prefs=W.profilePrefs(anim)
 assert.equal(prefs.startPage,'/production?mode=shot')
 assert.deepEqual(W.modifiedKeys(prefs,anim),[])
 assert.deepEqual(W.modifiedKeys({...prefs,folderTileSize:'lg'},anim),['folderTileSize'])
 assert.equal(W.findProfile({source:'project',id:'gone'},[],[]),null)
})
test('saving a profile replaces one of the same name and keeps ids unique',()=>{
 const prefs=W.resolvePrefs({launcher:'full'})
 let r=W.upsertProfile([],'Mon Lookdev é',prefs)
 assert.equal(r.id,'mon_lookdev_e')
 r=W.upsertProfile(r.list,'mon lookdev é',W.resolvePrefs({launcher:'compact'}))
 assert.equal(r.list.length,1)
 assert.equal(r.list[0].prefs.launcher,'compact')
 assert.equal(W.profileId('Mon Lookdev é',['mon_lookdev_e']),'mon_lookdev_e_2')
})
test('every built-in profile is valid and resolves to complete prefs',()=>{
 for(const p of W.BUILTIN_PROFILES){
  assert.deepEqual(W.sanitizePrefs(p.prefs),p.prefs,p.id)
  assert.deepEqual(Object.keys(W.profilePrefs(p)).sort(),Object.keys(W.DEFAULT_PREFS).sort())
 }
})
