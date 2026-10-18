"""Refresh the public calendar; network/validation errors preserve the previous snapshot."""
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from io import BytesIO
import argparse
import json
import os
import re
import urllib.request
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
LOGIN='mhatreanuj57-alt'
SOURCE=f'https://github.com/users/{LOGIN}/contributions'
COLORS=['#E5DFD4','#FFD1C7','#FFA08C','#FF5A3D','#10100F']
INK,MUTED,LIME='#10100F','#60605B','#D7FF36'


class Calendar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells,self.counts=[],{}
        self.tooltip,self.parts=None,[]

    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='td' and 'ContributionCalendar-day' in a.get('class','').split() and a.get('data-date'):
            self.cells.append((a['data-date'],a.get('id'),int(a['data-level'])))
        if tag=='tool-tip':self.tooltip,self.parts=a.get('for'),[]

    def handle_data(self,data):
        if self.tooltip:self.parts.append(data)

    def handle_endtag(self,tag):
        if tag=='tool-tip' and self.tooltip:
            value=' '.join(self.parts).strip()
            m=re.match(r'([\d,]+) contributions?\b',value)
            if m:self.counts[self.tooltip]=int(m[1].replace(',',''))
            elif value.startswith('No contributions'):self.counts[self.tooltip]=0
            self.tooltip=None

    def days(self,minimum=300):
        days=[]
        for iso,ident,level in self.cells:
            date.fromisoformat(iso)
            if ident not in self.counts or level not in range(5):raise ValueError(f'Missing count or invalid level: {iso}')
            count=self.counts[ident]
            if (count==0)!=(level==0):raise ValueError(f'Inconsistent count and color: {iso}')
            days.append({'date':iso,'count':count,'level':level})
        days.sort(key=lambda d:d['date'])
        if not minimum<=len(days)<=371 or len({d['date'] for d in days})!=len(days):raise ValueError('Incomplete/duplicate calendar')
        if any(date.fromisoformat(b['date'])-date.fromisoformat(a['date'])!=timedelta(days=1) for a,b in zip(days,days[1:])):raise ValueError('Calendar has a gap')
        return days


def statistics(days):
    run=best=0
    for d in days:
        run=run+1 if d['count'] else 0
        best=max(best,run)
    return {'contributions':sum(d['count'] for d in days),'activeDays':sum(d['count']>0 for d in days),
            'longestRun':best,'busiestDay':max(days,key=lambda d:d['count'])}


def fetch():
    req=urllib.request.Request(SOURCE,headers={'User-Agent':'Anuj-profile-calendar','Accept-Language':'en-US'})
    with urllib.request.urlopen(req,timeout=30) as response:
        parser=Calendar();parser.feed(response.read().decode('utf-8'))
    days=parser.days()
    def api(path):
        req=urllib.request.Request('https://api.github.com/'+path,headers={'User-Agent':'Anuj-profile-public-stats','Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
    user=api('users/'+LOGIN)
    if user['login']!=LOGIN or user['id']!=286920772:raise ValueError('Unexpected account')
    repos=[]
    for page in range(1,(user['public_repos']+99)//100+1):
        repos.extend(api(f'users/{LOGIN}/repos?type=owner&per_page=100&page={page}'))
    if len(repos)!=user['public_repos'] or any(r['owner']['login']!=LOGIN or r['private'] for r in repos):raise ValueError('Incomplete public repository list')
    return {'login':LOGIN,'source':SOURCE,'method':'unauthenticated public GitHub calendar',
            'fetchedAt':datetime.now(timezone.utc).isoformat(),'from':days[0]['date'],'to':days[-1]['date'],
            'statistics':statistics(days),'days':days,
            'repositoryStats':{'source':f'https://api.github.com/users/{LOGIN}','publicRepositories':user['public_repos'],
                               'repositoryStars':sum(r['stargazers_count'] for r in repos),'followers':user['followers']}}


def caption(data):
    s=data['statistics']
    return (f"**{s['contributions']} public contributions** · **{s['activeDays']} active days** · **{s['longestRun']}-day longest active run**\n\n"
            f"{data['from']} to {data['to']}; fetched {data['fetchedAt'][:10]} UTC. "
            f"[Live calendar](https://github.com/{LOGIN}?tab=overview#contributions) · "
            '[Snapshot data](assets/activity.json) · [Still image](assets/activity-static.png).\n\n'
            f"**{data['repositoryStats']['publicRepositories']} public repositories** · "
            f"**{data['repositoryStats']['repositoryStars']} repository stars** · **{data['repositoryStats']['followers']} followers** "
            '(public GitHub API, same snapshot).')


def render(data):
    base=Image.open(ROOT/'assets/activity-frame.png').convert('RGB');draw=ImageDraw.Draw(base)
    small=ImageFont.load_default(size=12);tiny=ImageFont.load_default(size=11);number=ImageFont.load_default(size=35)
    s=data['statistics']
    values=[s['contributions'],s['activeDays'],s['longestRun'],s['busiestDay']['count']]
    details=[f"{data['from'][:7]} / {data['to'][:7]}",f"of {len(data['days'])} days",'consecutive days',s['busiestDay']['date']]
    for i,(value,detail) in enumerate(zip(values,details)):
        draw.text((610+i*150,74),str(value),font=number,fill=INK)
        draw.text((610+i*150,112),detail,font=tiny,fill=MUTED)
    draw.text((56,374),f"Public GitHub calendar / @{LOGIN} / fetched {data['fetchedAt'][:10]} UTC",font=tiny,fill=MUTED)
    offset=(date.fromisoformat(data['from']).weekday()+1)%7;months=[]
    for i,d in enumerate(data['days']):
        week,row=divmod(i+offset,7);x,y=118+week*19,182+row*19
        draw.rectangle((x,y,x+14,y+14),fill=COLORS[d['level']])
        month=d['date'][:7]
        if not months or month!=months[-1][1]:months.append((x,month))
    if len(months)>1 and months[1][0]-months[0][0]<55:months.pop(0)
    for x,month in months:draw.text((x,160),date.fromisoformat(month+'-01').strftime('%b'),font=small,fill=MUTED)
    weeks=(len(data['days'])+offset+6)//7
    route=[(118+w*19+7,182+r*19+7) for w in range(weeks) for r in (range(7) if w%2==0 else range(6,-1,-1))]
    # shortcut: a scan trail preserves calendar values; it does not erase contributions as it passes.
    frames=[]
    for frame in range(180):
        im=base.copy();d=ImageDraw.Draw(im);head=(frame/180)*len(route)
        for tail in range(8,-1,-1):
            at=(head-tail*1.15)%len(route);a,b=route[int(at)],route[(int(at)+1)%len(route)];f=at-int(at)
            x,y=a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f;rad=5-tail*.28
            d.rectangle((x-rad,y-rad,x+rad,y+rad),fill=LIME if tail==0 else COLORS[max(1,4-tail//3)],outline=INK if tail==0 else None)
        frames.append(im)
    palette_sheet=Image.new('RGB',(base.width,base.height+20),LIME);palette_sheet.paste(base,(0,0))
    palette=palette_sheet.quantize(colors=128)
    indexed=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in frames];gif=BytesIO()
    indexed[0].save(gif,format='GIF',save_all=True,append_images=indexed[1:],duration=70,loop=0,optimize=True,disposal=1)
    png=BytesIO();base.save(png,format='PNG')
    glance=Image.open(ROOT/'assets/glance-frame.png').convert('RGB');gd=ImageDraw.Draw(glance)
    for i,value in enumerate([data['repositoryStats']['publicRepositories'],data['repositoryStats']['repositoryStars'],data['repositoryStats']['followers']]):
        gd.text((32+i*174,89),str(value),font=number,fill=INK)
    gd.text((32,170),f"Public GitHub API / {data['fetchedAt'][:10]} UTC",font=small,fill=MUTED)
    glance_png=BytesIO();glance.save(glance_png,format='PNG')
    return gif.getvalue(),png.getvalue(),glance_png.getvalue()


def self_check():
    p=Calendar();p.feed('<td data-level="1" id="a" data-date="2026-10-17" class="other ContributionCalendar-day"></td>'
        '<td class="ContributionCalendar-day" data-date="2026-10-18" id="b" data-level="0"></td>'
        '<tool-tip for="a">1 contribution on Oct 17.</tool-tip><tool-tip for="b">No contributions on Oct 18.</tool-tip>')
    days=p.days(minimum=2);assert statistics(days)['contributions']==1 and statistics(days)['longestRun']==1
    del p.counts['a']
    try:p.days(minimum=2)
    except ValueError:pass
    else:raise AssertionError('Missing counts must fail')
    print('PASS: counts, singular/no contributions, dates, missing-count rejection')


def main():
    args=argparse.ArgumentParser();args.add_argument('--check',action='store_true')
    if args.parse_args().check:self_check();return
    data=fetch();readme=(ROOT/'README.md').read_text(encoding='utf-8')
    updated,n=re.subn(r'<!-- activity:start -->.*?<!-- activity:end -->','<!-- activity:start -->\n'+caption(data)+'\n<!-- activity:end -->',readme,flags=re.S)
    if n!=1:raise ValueError('Exactly one native activity summary required')
    gif,png,glance=render(data);assert len(gif)<5_000_000
    files={'assets/activity.json':json.dumps(data,indent=2).encode()+b'\n','assets/activity.gif':gif,
           'assets/activity-static.png':png,'assets/github-glance.png':glance,'README.md':updated.encode('utf-8')}
    for name,content in files.items():
        target=ROOT/name;target.with_suffix(target.suffix+'.tmp').write_bytes(content)
    for name in files:
        target=ROOT/name;os.replace(target.with_suffix(target.suffix+'.tmp'),target)
    print('Updated public activity:',data['statistics'])


if __name__=='__main__':main()
