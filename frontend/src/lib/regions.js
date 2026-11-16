// Ghana's sixteen regions, in alphabetical order.
//
// This is a static copy of backend/app/data/foods.py::REGION_ZONES, kept here
// rather than fetched because the enrolment form has to work with no signal.
// A backend test reads this file and fails if the two lists differ, so adding
// a region in one place and forgetting the other cannot ship.
export const REGIONS = [
  'Ahafo', 'Ashanti', 'Bono', 'Bono East', 'Central', 'Eastern',
  'Greater Accra', 'North East', 'Northern', 'Oti', 'Savannah',
  'Upper East', 'Upper West', 'Volta', 'Western', 'Western North',
]
