const ActivityDates=require('../activity-dates.js');
const {Store}=require('../activity-data.js');
const ActivityView=require('../activity-view.js');
// Real modules with explicit test dependencies; no source slicing for rendering or dates.
function prepare(c){
 c.ActivityDates=ActivityDates;
 c.activityStore ||= new Store(url=>c.clubApi.request(url));
 for(const day of c.activityPayload?.neighborDays||c.activityPayload?.days||[])c.activityStore.merge([day]);
 const platform={setTimeout,clearTimeout,...c};
 const view=ActivityView.create(c,platform);
 for(const [name,fn] of Object.entries(view))if(!c[name])c[name]=fn;
 return c;
}
module.exports={prepare,ActivityDates,ActivityView,Store};
