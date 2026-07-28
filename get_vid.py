import urllib.request, re
req = urllib.request.Request('https://www.pexels.com/search/videos/smartphone/', headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    match = re.search(r'(https://videos\.pexels\.com/video-files/[^\"\'\s]+\.mp4)', html)
    if match:
        print(match.group(1))
    else:
        print('No video found')
except Exception as e:
    print(e)
