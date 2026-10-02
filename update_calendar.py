#!/usr/bin/env python3
"""Build a subscription calendar from the public SWHL schedule (stdlib only)."""
import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

SOURCE = 'https://swhl.ru/tournament/1067241/calendar'
TEAM = 'Silk Way Star'
BASE_YEAR = 2026
ROOT = Path(__file__).resolve().parent
MOSCOW = timezone(timedelta(hours=3))
MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
          'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
          'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c
                                 for c in self.children).split())

    def find(self, cls):
        result = []
        for c in self.children:
            if isinstance(c, Node):
                if cls in c.attrs.get('class', '').split():
                    result.append(c)
                result.extend(c.find(cls))
        return result

    def one(self, cls):
        matches = self.find(cls)
        if len(matches) != 1:
            raise ValueError(f'Expected one {cls}, found {len(matches)}')
        return matches[0]


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def utc(dt):
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def parse(html):
    doc = Document(html).root
    events = {}
    year, previous_month = BASE_YEAR, 0
    for unit in doc.find('timetable__unit'):
        label = unit.one('timetable__head-text').text().lower()
        match = re.match(r'(\d+)\s+([а-яё]+)(?:\s+(\d{4}))?', label)
        if not match or match[2] not in MONTHS:
            raise ValueError(f'Unknown date: {label}')
        month = MONTHS[match[2]]
        if match[3]:
            year = int(match[3])
        elif previous_month and month < previous_month:
            year += 1
        previous_month = month
        for item in unit.find('timetable__item'):
            teams = [n.text() for n in item.find('timetable__team-name')]
            if TEAM not in teams:
                continue
            if len(teams) != 2:
                raise ValueError(f'Invalid teams: {teams}')
            time = item.one('timetable__time').text()
            if not re.fullmatch(r'\d{1,2}:\d{2}', time):
                raise ValueError(f'Invalid start time: {time}')
            hour, minute = map(int, time.split(':'))
            start = datetime(year, month, int(match[1]), hour, minute, tzinfo=MOSCOW)
            path = item.one('timetable__score').attrs['href']
            match_id = re.fullmatch(r'/match/(\d+)', path)
            if not match_id:
                raise ValueError(f'Unknown match URL: {path}')
            key = match_id[1]
            if key in events:
                raise ValueError(f'Duplicate match {key}')
            events[key] = {
                'summary': ' — '.join(teams),
                'start': utc(start),
                'location': item.one('timetable__place').attrs.get('title', '').strip(),
                'round': item.one('timetable__round').text(),
                'url': 'https://swhl.ru' + path,
            }
    if not events:
        raise ValueError('No team matches found; retaining the last good calendar')
    return events


def escape(text):
    return text.replace('\\', '\\\\').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold(line):
    chunks, chunk, size = [], '', 0
    for char in line:
        n = len(char.encode('utf-8'))
        if size + n > 75:
            chunks.append(chunk)
            chunk, size = ' ', 1
        chunk += char
        size += n
    chunks.append(chunk)
    return '\r\n'.join(chunks)


def render(events, duration):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
             'PRODID:-//Sibek//Silk Way Star Calendar//RU',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             'X-WR-CALNAME:Silk Way Star · SWHL 2026/27',
             'X-WR-TIMEZONE:Europe/Moscow',
             'REFRESH-INTERVAL;VALUE=DURATION:PT6H', 'X-PUBLISHED-TTL:PT6H']
    for key, event in sorted(events.items(), key=lambda p: p[1]['data']['start']):
        data = event['data']
        description = f"{data['round']}\nВремя начала — московское.\nИсточник: {data['url']}"
        if duration:
            description += f'\nДлительность {duration} мин. указана приблизительно; сайт сообщает только время начала.'
        lines.extend(['BEGIN:VEVENT', f'UID:swhl-{key}@sibek.github.io',
                      f"DTSTAMP:{event['modified']}", f"LAST-MODIFIED:{event['modified']}",
                      f"SEQUENCE:{event['sequence']}", f"DTSTART:{data['start']}"])
        if duration:
            start = datetime.strptime(data['start'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            lines.append('DTEND:' + utc(start + timedelta(minutes=duration)))
        lines.extend(['SUMMARY:' + escape(data['summary']),
                      'LOCATION:' + escape(data['location']),
                      'DESCRIPTION:' + escape(description),
                      'URL:' + data['url'], 'STATUS:CONFIRMED', 'TRANSP:OPAQUE',
                      'BEGIN:VALARM', 'ACTION:DISPLAY', 'TRIGGER:-PT1H',
                      'DESCRIPTION:' + escape(data['summary']), 'END:VALARM', 'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(fold(line) for line in lines) + '\r\n').encode('utf-8')


def write_if_changed(path, data):
    if path.exists() and path.read_bytes() == data:
        return
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html', type=Path, help='Use a saved source page')
    parser.add_argument('--duration', type=int, default=120, help='Approximate minutes; 0 omits the end time')
    args = parser.parse_args()
    if args.duration < 0:
        raise ValueError('Duration cannot be negative')
    if args.html:
        html = args.html.read_text(encoding='utf-8')
    else:
        request = Request(SOURCE, headers={'User-Agent': 'SilkWayStarCalendar/1.0 (+https://github.com/Sibek/silk-way-star)'})
        with urlopen(request, timeout=30) as response:
            html = response.read().decode('utf-8')
    parsed = parse(html)
    state_path = ROOT / 'schedule.json'
    old = json.loads(state_path.read_text()) if state_path.exists() else {}
    missing = set(old) - set(parsed)
    if missing:
        raise ValueError(f'Matches disappeared: {sorted(missing)}. Manual review required; retaining the last good calendar.')
    now = utc(datetime.now(timezone.utc))
    events = {}
    for key, data in parsed.items():
        data['duration_minutes'] = args.duration
        previous = old.get(key)
        if previous and previous['data'] == data:
            events[key] = previous
        else:
            events[key] = {'data': data, 'sequence': previous['sequence'] + 1 if previous else 0, 'modified': now}
    content = render(events, args.duration)
    write_if_changed(ROOT / 'public' / 'silk-way-star.ics', content)
    write_if_changed(state_path, (json.dumps(events, ensure_ascii=False, indent=2) + '\n').encode())
    print(f'{len(events)} matches; {sum(old.get(k) != v for k, v in events.items())} changed')


if __name__ == '__main__':
    main()
