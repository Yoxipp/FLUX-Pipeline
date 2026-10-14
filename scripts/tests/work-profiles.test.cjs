const {test}=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs'),ts=require('typescript')
const source=fs.readFileSync('app/src/lib/workProfiles.ts','utf8')
const mod={exports:{}}
new Function('exports','module',ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(mod.exports,mod)
const W=mod.exports

test('first load uses defaults and drops the old Folder Manager prefs',()=>{
 const u=W.readUserWorkProfile({prefs:{folderTileSize:'lg',folderLayout:'quad'}})
 assert.deepEqual(u.active,W.DEFAULT_REF)
 assert.deepEqual(u.prefs,W.DEFAULT_PREFS)
 assert.equal('folderTileSize' in u.prefs,false)
 assert.equal(u.prefs.notifyMention,true)
 assert.equal(u.prefs.notifyPublish,false)
 assert.deepEqual(u.custom,[])
})
test('saved prefs are validated and corrupt data falls back to defaults',()=>{
 const u=W.readUserWorkProfile({active:{source:'user',id:'me'},prefs:{productionDepartments:' layout, anim ,LAYOUT',launcher:'huge',startPage:'/nowhere',notifyError:'yes'},custom:[{id:'me',name:'Moi',prefs:{launcher:'full'}},{id:'me',name:'dup'},{name:'no id'}]})
 assert.deepEqual(u.active,{source:'user',id:'me'})
 assert.equal(u.prefs.productionDepartments,'LAYOUT,ANIM')
 assert.equal(u.prefs.launcher,'compact')
 assert.equal(u.prefs.startPage,'/')
 assert.equal(u.prefs.notifyError,false)
 assert.deepEqual(u.custom,[{id:'me',name:'Moi',prefs:{launcher:'full'}}])
 assert.deepEqual(W.readUserWorkProfile('garbage').active,W.DEFAULT_REF)
})
test('applying a profile then tweaking shows exactly the modified keys',()=>{
 const anim=W.findProfile({source:'builtin',id:'animation'},[],[])
 const prefs=W.profilePrefs(anim)
 assert.equal(prefs.startPage,'/production?mode=shot')
 assert.deepEqual(W.modifiedKeys(prefs,anim),[])
 assert.deepEqual(W.modifiedKeys({...prefs,notifyPublish:true},anim),['notifyPublish'])
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
const deps=['Layout','Animation','FX','Lighting'].map(name=>({name}))
test('a profile filters the Show columns but never empties the table',()=>{
 assert.deepEqual(W.visibleDepartments(deps,'').map(d=>d.name),['Layout','Animation','FX','Lighting'])
 assert.deepEqual(W.visibleDepartments(deps,'LAYOUT,ANIMATION,RIGGING').map(d=>d.name),['Layout','Animation'])
 // Only asset departments in the preset: shot table shows everything.
 assert.equal(W.visibleDepartments(deps,'MODELING').length,4)
})
test('ticking columns by hand overrides the preset and keeps the other mode',()=>{
 let pref='LAYOUT,ANIMATION,RIGGING'
 pref=W.toggleDepartment(deps,pref,'FX')
 assert.equal(pref,'RIGGING,LAYOUT,ANIMATION,FX')
 pref=W.toggleDepartment(deps,pref,'Layout')
 assert.deepEqual(W.visibleDepartments(deps,pref).map(d=>d.name),['Animation','FX'])
 assert.ok(W.splitDepartments(pref).includes('RIGGING'))
 // The last column cannot be hidden.
 assert.equal(W.toggleDepartment(deps,'FX','FX'),'FX')
 // From "all": unticking one lists the others; ticking it back returns to all.
 const one=W.toggleDepartment(deps,'','FX')
 assert.equal(one,'LAYOUT,ANIMATION,LIGHTING')
 assert.equal(W.toggleDepartment(deps,one,'FX'),'')
 assert.equal(W.showAllDepartments(deps,'LAYOUT,RIGGING'),'RIGGING')
})
