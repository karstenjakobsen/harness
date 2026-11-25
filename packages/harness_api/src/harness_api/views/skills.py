from ..models.activity import CallReference
from ..models.skills import SkillRevision, SkillSummary

# The HTTP skill reads expose the same records as the public model.
SkillSummaryView = SkillSummary
SkillRevisionView = SkillRevision
SkillReadingCallView = CallReference
