import os, traceback
_R = os.environ.get('RENDER_DIR') or os.getcwd()   # render/ of THIS clone (run_all.sh exports RENDER_DIR)
try: exec(open(_R + '/models/gen_models.py').read())
except Exception: traceback.print_exc()
