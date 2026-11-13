import os
p = 'd:/updated3/keka-hrms-clone/static/img'
for f in sorted(os.listdir(p)):
    print(f, os.path.getsize(os.path.join(p, f)))