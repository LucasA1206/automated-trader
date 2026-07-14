import os
import sys

# Add backend directory to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from backend.jobs import job_manual_scan

print('Running job_manual_scan...')
job_manual_scan()
print('Done!')
