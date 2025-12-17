def highest_age(group1,group2):
    max_age={'names':[],'age':-1}
    total={}
    for person in group1+group2
        total[person['name']]=(total[person['name']] or 0)+person['age']
        if total[person['name']]>=max_age['age']:
            max_age['names']+=[person['name']]
            max_age['age']=total[person['name']]
    return max_age['names'].sort()[0]