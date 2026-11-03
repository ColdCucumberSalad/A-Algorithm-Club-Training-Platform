(() => {
  let version=1;
  let seated=true,capacity={players:1,limit:10,available:9};
  const seats=Array.from({length:6},(_,i)=>({user_id:String(i+1),number:i,name:['林同学','周同学','练习机器人 1','陈同学','练习机器人 2','李同学'][i],is_bot:i===2||i===4,stack:1000,ready:false,leaving:false,cards:[],card_count:0,folded:false,bet:0,in_hand:false}));
  let room={id:'fixture',name:'周末练习桌',mode:'friendly',max_players:6,buy_in:1000,big_blind:10,version,closed:false,seats,hand_number:0,dealer:3,street:'waiting',board:[],pot:0,actor:null,deadline:null,result:null,log:[],actions:null};
  const actions={call:20,check:false,raise:true,min_raise_to:40,max_raise_to:1000,all_in:true};
  let last=[];
  function next(type){
    if(type==='nine'){room.max_players=9;room.seats=Array.from({length:9},(_,i)=>({...seats[i%6],user_id:String(i+1),number:i,name:i===0?'林同学':['周同学','陈同学','赵同学','孙同学','钱同学','李同学','吴同学','郑同学'][i-1]}));type='deal';}
    if(type==='deal'){room={...room,hand_number:room.hand_number+1,street:'preflop',board:[],pot:15,actor:'1',deadline:Date.now()/1000+45,result:null,actions:{...actions}};room.seats=room.seats.map((s,i)=>({...s,stack:1000-(i===4?5:i===5?10:0),cards:i===0?['14s','13s']:[],card_count:2,folded:false,in_hand:true,bet:i===4?5:i===5?10:0}));}
    if(type==='bet'){room.seats[0].stack-=60;room.seats[0].bet+=60;room.pot+=60;room.actor='2';room.actions=null;room.deadline=Date.now()/1000+45;room.log.push('林同学 加注至 60');}
    if(type==='flop'){room.street='flop';room.board=['10s','11s','12s'];room.seats.forEach(s=>s.bet=0);room.pot=180;room.actor='1';room.actions={...actions,call:0,check:true,min_raise_to:10};room.deadline=Date.now()/1000+45;room.log.push('翻牌');}
    if(type==='showdown'){room.street='finished';room.board=['10s','11s','12s','2h','7d'];room.actor=null;room.deadline=null;room.actions=null;room.result={payouts:{'1':180},pots:[{amount:180,winners:['1']}],showdown:true,hands:{'1':'同花顺','2':'一对'}};room.seats[0].stack+=180;room.seats.forEach((s,i)=>{s.bet=0;s.cards=i===0?['14s','13s']:['9h','9d'];s.ready=false;});room.log.push('林同学 赢得 180');}
    room.version=++version;
  }
  window.PokerPreview={next,get room(){return structuredClone(room)},get requests(){return last},setRoom(value){room=structuredClone(value);room.version=++version;},setCapacity(value){capacity=structuredClone(value);},setSeated(value){seated=value;}};
  window.CurrencyModule={getCurrencyData:()=>({balance:1280}),syncBalance:()=>{}};
  window.clubApi={request:async(path,options)=>{
    const data=options?.body?JSON.parse(options.body):null;last.push({path,data});
    if(data?.action==='leave'&&room.mode==='practice'){room={...room,closed:true,seats:[],actions:null,actor:null};seated=false;room.version=++version;}
    if(data){if(data.action==='ready')next('deal');else if(data.action==='raise'||data.action==='call')next('bet');else if(data.action==='check')next('showdown');else if(data.action==='fold'){room.seats[0].folded=true;room.actor='2';room.actions=null;room.version=++version;}}
    return {ok:true,json:async()=>path.endsWith('/fixture')?{room:structuredClone(room),user_id:1,balance:1280,server_time:Date.now()/1000}:{enabled:true,current_room:seated?'fixture':null,capacity:structuredClone(capacity),user_id:1,balance:1280,rooms:[]}};
  }};
})();
