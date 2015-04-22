from django.core.management.base import BaseCommand
from django.db.models import Min

from protein.models import Protein
from residue.models import Residue
from residue.models import ResidueGenericNumber
from structure.models import Structure
from protein.models import ProteinSegment
from common.alignment import Alignment
from common.models import WebLink

from collections import OrderedDict
import re
from itertools import chain
import pprint



class Command(BaseCommand):
    
    def handle(self, *args, **options):
        Homology_model = HomologyModeling('gp139_human', 'Inactive')
        multi_alignment = Homology_model.run_pairwise_alignment()
        main_template = Homology_model.select_main_template(multi_alignment)
        main_alignment = Homology_model.run_main_alignment(Homology_model.reference_protein, main_template)    
        non_conserved_alignment = Homology_model.run_non_conserved_switcher(main_alignment)       
    
        self.stdout.write(Homology_model.statistics, ending='')


class HomologyModeling(object):
    ''' Class to build homology models for GPCRs. 
    
        @param reference_id: str, protein id \n
        @param state: str, endogenous ligand state of reference \n
        @param query_states: list, list of endogenous ligand states to be applied for template search, default: same as reference \n
        @param testing: boolean, test program with existing structure, default: False \n
    '''
    def __init__(self, reference_id, state, query_states='default', testing=False):
        self.reference_id = reference_id
        self.state = state
        self.query_states = query_states
        self.testing = testing
        self.statistics = CreateStatistics(self.reference_id)
        
    def __repr__(self):
        return "<{}, {}>".format(self.reference_id, self.state)
        
    def get_receptor_data(self, receptor):
        ''' Get Protein object of receptor.
        
            @param receptor: str, protein id
        '''
        self.reference_protein = Protein.objects.get(entry_name=self.reference_id)
        self.uniprot_id = self.reference_protein.accession
        self.reference_sequence = self.reference_protein.sequence
        self.statistics.add_info('uniprot_id',self.uniprot_id)
        return self.reference_protein

    def get_structure_data(self, pdb):
        ''' Get Structure object based on pdb code.
        
            @param pdb: str, pdb code
        '''
        structure = Structure.objects.get(pdb_code_id__index=pdb)
        return structure

    def get_targets_structure_data(self, state, query_states):
        ''' Get all target Structure objects based on endogenous ligand state. Returns QuerySet object.
        
            @param state: str, endogenous ligand state \n
            @param query_states: list, list of endogenous ligand states to be applied for template search, default: same as reference 
        '''
        self.state = state
        self.query_states = query_states

        if self.query_states == 'default':          
            if self.testing == False:
                self.structures_datatable = Structure.objects.filter(state__name=self.state).order_by('protein__parent','resolution').distinct('protein__parent')
            elif self.testing == True:
                self.structures_datatable = Structure.objects.filter(state__name=self.state).order_by('protein__parent','resolution').distinct('protein__parent').exclude(protein__parent__entry_name=self.reference_id)
        elif type(self.query_states) is list:
            for query_state in self.query_states:
                assert (Structure.objects.filter(state__name=query_state)), "InputError: query state argument {} is not valid. No such entry in the database.".format(query_state)
            if self.testing == False:
                self.structures_datatable = Structure.objects.filter(state__name__in=self.query_states).order_by('protein__parent','resolution').distinct('protein__parent')       
            elif self.testing == True:
                self.structures_datatable = Structure.objects.filter(state__name__in=self.query_states).order_by('protein__parent','resolution').distinct('protein__parent').exclude(protein__parent__entry_name=self.reference_id)
        
        return self.structures_datatable        
        
    def get_targets_protein_data(self, structures_data):
        ''' Get all target Protein objects based on Structure objects. Returns a list of Protein objects.
        
            @param structures_data: QuerySet, query set of Structure objects. Output of get_targets_structure_data function.
        '''
        plist = []
        for target in structures_data:
            plist.append(Protein.objects.get(id=target.protein.parent.id))
        return plist
        
    def run_pairwise_alignment(self, segments='default_7TM', reference=True, calculate_similarity=True, targets=None):
        ''' Creates pairwise alignment between reference and target receptor(s).
            Returns Alignment object.
            
            @param segments: list, list of segments to use, e.g.: ['TM1','IL1','TM2','EL1'] \n
            @param reference: boolean, if True, reference receptor is used as reference, default: True.
            @param calculate_similarity: boolean, if True, call Alignment.calculate_similarity, default: True.
            @param targets: list, list of Protein objects to use as targets. By default it uses all targets with state
            specified when initializing the HomologyModeling() class.
        '''
        self.segments = segments
        if not targets:
            targets = self.get_targets_protein_data(self.get_targets_structure_data(self.state, self.query_states))       
        
        # core functions from alignment.py
        a = Alignment()
        if reference==True:
            a.load_reference_protein(self.get_receptor_data(self.reference_id))
        a.load_proteins(targets)
        if self.segments=='default_7TM':
            self.segments = ProteinSegment.objects.filter(slug__in=['TM1','TM2','TM3','TM4','TM5','TM6','TM7'])
            a.load_segments(self.segments)
        else:
            self.segments = ProteinSegment.objects.filter(slug__in=self.segments)
            a.load_segments(self.segments)
        a.build_alignment()
        if calculate_similarity==True:
            a.calculate_similarity()   
        return a
    
    def select_main_template(self, alignment):
        ''' Select main template for homology model based on highest sequence similarity. Returns Structure object of main template.
        
            @param alignment: Alignment, aligment object where the first protein is the reference. Output of pairwise_alignment function.
        '''
        self.similarity_table = self.create_ordered_similarity_table(self.state, self.query_states, self.structures_datatable)
 
        main_structure = list(self.similarity_table.items())[0][0]       
        main_structure_protein = Protein.objects.get(id=main_structure.protein.parent.id)
        
        self.main_pdb_id = main_structure.pdb_code.index #str(WebLink.objects.get(id=main_structure.pdb_code_id))[-4:]
        self.main_template_sequence = main_structure_protein.sequence
        if len(main_structure.preferred_chain)>1:
            self.main_template_preferred_chain = main_structure.preferred_chain[0]
        else:
            self.main_template_preferred_chain = main_structure.preferred_chain   
        
        self.statistics.add_info("main_template", self.main_pdb_id)
        self.statistics.add_info("preferred_chain", self.main_template_preferred_chain)
        
        return main_structure
        
    def run_main_alignment(self, reference, main_template, segments='default_7TM'):
        ''' Creates an alignment between reference (Protein object) and main_template (Structure object) 
            where matching residues are depicted with the one-letter residue code, mismatches with '.', 
            gaps with '-', gaps due to shorter sequences with 'x'. returns a AlignedReferenceAndTemplate class.
            
            @param reference: Protein object, reference receptor
            @param main_template: Structure object, main template
        '''
        
        main_template_protein = Protein.objects.get(id=main_template.protein_id)
        if segments=='default_7TM':
            a = self.run_pairwise_alignment(reference=False, calculate_similarity=False, targets=[reference, main_template_protein])
        else:
            self.segments = segments
            a = self.run_pairwise_alignment(segments=self.segments, reference=False, calculate_similarity=False, targets=[reference, main_template_protein])            
        ref = a.proteins[0].alignment
        temp = a.proteins[1].alignment
        reference_string, template_string, matching_string = '','',''   
        reference_dict = OrderedDict()
        template_dict = OrderedDict()
        segment_count = 0

        for ref_segment, temp_segment in zip(ref,temp):
            segment_count+=1
            for ref_position, temp_position in zip(ref_segment,temp_segment):
                
                if ref_position[1]!=False and temp_position[1]!=False:
                    if ref_position[0]==temp_position[0]:
                        reference_dict[ref_position[0]]=ref_position[2]
                        template_dict[temp_position[0]]=temp_position[2]
                        reference_string+=ref_position[2]
                        template_string+=temp_position[2]
                        if ref_position[2]==temp_position[2]:
                            matching_string+=ref_position[2]
                        else:
                            matching_string+='.'
                    else:
                        print("Error: Generic numbers don't align")
                            
                elif ref_position[1]!=False and temp_position[1]==False:
                    reference_dict[ref_position[0]]=ref_position[2]                    
                    reference_string+=ref_position[2]
                    if temp_position[2]=='-':
                        template_dict[temp_position[0]]='-'
                        template_string+='-'
                        matching_string+='-'
                    elif temp_position[2]=='_':
                        template_dict[temp_position[0]]='x'
                        template_string+='x'
                        matching_string+='x'
                        
                elif ref_position[2]=='-' and temp_position[1]!=False:
                    reference_dict[ref_position[0]]='-'
                    template_dict[temp_position[0]]=temp_position[2]
                    reference_string+='-'
                    template_string+=temp_position[2]
                    matching_string+='-'
                    
                elif ref_position[2]=='-' and temp_position[2]=='-':
                    reference_dict[ref_position[0]]='-'
                    template_dict[temp_position[0]]='-'
                    reference_string+='-'
                    template_string+='-'
                    matching_string+='-'  
            reference_dict["TM"+str(segment_count)+"_end"]='/'                     
            template_dict["TM"+str(segment_count)+"_end"]='/'  
            reference_string+='/'
            template_string+='/'
            matching_string+='/'

        main_alignment = AlignedReferenceAndTemplate(self.reference_id, self.main_pdb_id, reference_dict, template_dict, matching_string)           
        return main_alignment
        
    def run_non_conserved_switcher(self, alignment_input, switch_bulges=True, switch_constrictions=True):
        ''' Function to identify and switch non conserved residues in the alignment. Optionally,
            it can identify and switch bulge and constriction sites too. 
            
            @param alignment_input: AlignedReferenceAndTemplate, alignment of reference and main template with alignment string. \n
            @param switch_bulges: boolean, identify and switch bulge sites. Default = True.
            @param switch_constrictions: boolean, identify and switch constriction sites. Default = True.
        '''
        ref_length = 0
        non_cons_count = 0
        ref_bulge_list, temp_bulge_list, ref_const_list, temp_const_list = [],[],[],[]
        parse = GPCRDBParsingPDB()
        
        # bulges and constrictions
        if switch_bulges==True or switch_constrictions==True:
            self.similarity_table_all = self.create_ordered_similarity_table(self.state, ['Active','Inactive'], self.structures_datatable)

            for ref_res, temp_res, aligned_res in zip(alignment_input.reference_dict, alignment_input.template_dict, alignment_input.aligned_string):
                
                gn = ref_res
                gn_TM = parse.gn_num_extract(gn, 'x')[0]
                gn_num = parse.gn_num_extract(gn, 'x')[1]
                
                if aligned_res=='-':
                    if alignment_input.reference_dict[ref_res]=='-' and alignment_input.reference_dict[parse.gn_indecer(gn,'x',-1)] not in ['-','/'] and alignment_input.reference_dict[parse.gn_indecer(gn,'x',+1)] not in ['-','/']: 
    
                        # bulge in template
                        if len(str(gn_num))==3:
                            if switch_bulges==True:
                                temp_bulge_list.append({gn:alignment_input.template_dict[temp_res]})
    
                        # constriction in reference
                        else:
                            if switch_constrictions==True:
                                ref_const_list.append({parse.gn_indecer(gn, 'x', -1)+'-'+parse.gn_indecer(gn, 'x', +1):alignment_input.reference_dict[parse.gn_indecer(gn, 'x', -1)]+'-'+alignment_input.reference_dict[parse.gn_indecer(gn, 'x', +1)]})
                    
                    elif alignment_input.template_dict[temp_res]=='-' and alignment_input.template_dict[parse.gn_indecer(gn,'x',-1)] not in ['-','/'] and alignment_input.template_dict[parse.gn_indecer(gn,'x',+1)] not in ['-','/']: 
                        
                        # bulge in reference
                        if len(str(gn_num))==3:
                            if switch_bulges==True:
                                Bulge = Bulges()
                                bulge_template = Bulge.bulge_in_reference(gn, self.similarity_table_all)
                                ref_bulge_list.append({gn:Bulge.template})                                
                                                
                        # constriction in template
                        else:
                            if switch_constrictions==True:
                                temp_const_list.append({parse.gn_indecer(gn, 'x', -1)+'-'+parse.gn_indecer(gn, 'x', +1):alignment_input.template_dict[parse.gn_indecer(gn, 'x', -1)]+'-'+alignment_input.template_dict[parse.gn_indecer(gn, 'x', +1)]})
        
        
        # non-conserved residues
        for ref_res, temp_res, aligned_res in zip(alignment_input.reference_dict, alignment_input.template_dict, alignment_input.aligned_string):
            if ref_res!='-' and ref_res!='/':
                ref_length+=1   
            
            gn = ref_res
            gn_TM = parse.gn_num_extract(gn, 'x')[0]
            gn_num = parse.gn_num_extract(gn, 'x')[1]
            
            if aligned_res=='.':
                non_cons_count+=1                            
                 
    def create_ordered_similarity_table(self, state, query_states, structures_datatable):
        ''' Creates an ordered dictionary, where templates are sorted by similarity score.
        
            @param state: str, endogenous ligand state of reference \n
            @param query_states: list, endogenous ligand states of templates involved \n
            @param structures_datatable: QuerySet, involved template structures. Output of get_targets_structure_data
        '''
        structure_data = self.get_targets_structure_data(state, query_states=query_states) 
        target_list = self.get_targets_protein_data(structure_data)
        alignment_all = self.run_pairwise_alignment(targets=target_list)
        sim_table_all_temp = []
        similarity_table_all = OrderedDict()

        for i in range(1,len(alignment_all.proteins)):
            sim_table_all_temp.append([alignment_all.proteins[i],int(alignment_all.proteins[i].similarity)])
        sim_table_order = sorted(sim_table_all_temp, key=lambda x: x[1], reverse=True)
        for i in sim_table_order:
            matches = structure_data.order_by('protein__parent','resolution').distinct('protein__parent').filter(protein__parent=i[0].id)    
            similarity_table_all[list(matches)[0]] = i[1]
            
        return similarity_table_all
            
class Bulges(object):
    ''' Class to handle bulges in GPCR structures.
    '''
    def __init__(self):
        pass
    
    def bulge_in_reference(self, gn, similarity_table):
        ''' Searches for bulge template when bulge is in the reference receptor.
            
            @param gn: str, Generic number of bulge, e.g. 1x411 \n
            @param similarity_table: OrderedDict(), table of structures ordered by preference.
            Output of HomologyModeling().create_ordered_similarity_table().
        '''
        bulge_templates = []
        parse = GPCRDBParsingPDB()
        matches = Residue.objects.filter(generic_number__label=gn)
        for structure, value in similarity_table.items():  
            protein_name = Protein.objects.get(id=structure.protein.parent.id)
            try:                            
                for match in matches:
                    if match.protein==protein_name:
                        bulge_templates.append(structure)
            except:
                pass
        for temp in bulge_templates:
            try:
                alt_bulge = GPCRDBParsingPDB.fetch_lines_from_pdb(parse, temp, str(temp.preferred_chain)[0], [parse.gn_indecer(gn,'x',-2),parse.gn_indecer(gn,'x',-1),gn,parse.gn_indecer(gn,'x',+1),parse.gn_indecer(gn,'x',+2)])
                self.template = temp              
                break
            except:
                self.template = None
                
        if alt_bulge:
            return alt_bulge
        else:
            return None
            
    def bulge_in_template(self, gn, similarity_table):
        ''' Searches for subtemplate when bulge is in the template receptor.
            
            @param gn: str, Generic number of bulge, e.g. 1x411 \n
            @param similarity_table: OrderedDict(), table of structures ordered by preference.
            Output of HomologyModeling().create_ordered_similarity_table().
        '''
        pass

class AlignedReferenceAndTemplate(object):
    ''' Representation class for HomologyModeling.run_main_alignment() function. 
    '''
    def __init__(self, reference_id, template_id, reference_dict, template_dict, aligned_string):
        self.reference_id = reference_id
        self.template_id = template_id
        self.reference_dict = reference_dict
        self.template_dict = template_dict
        self.aligned_string = aligned_string
        
    def __repr__(self):
        return "<{}, {}>".format(self.reference_id,self.template_id)
        
class GPCRDBParsingPDB(object):
    ''' Class to manipulate cleaned pdb files of GPCRs.
    '''
    def __init__(self):
        pass
    
    def gn_num_extract(self, gn, delimiter):
        ''' Extract TM number and position for formatting.
        
            @param gn: str, Generic number \n
            @param delimiter: str, character between TM and position (usually 'x')
        '''
        try:
            split = gn.split(delimiter)
            return int(split[0]), int(split[1])
        except:
            return '/', '/'
            
    def gn_indecer(self, gn, delimiter, direction):
        ''' Get an upstream or downstream generic number from reference generic number.
        
            @param gn: str, Generic number \n
            @param delimiter: str, character between TM and position (usually 'x') \n 
            @param direction: int, n'th position from gn (+ or -)
        '''
        split = self.gn_num_extract(gn, delimiter)
        if split[0]!='/':
            if len(str(split[1]))==2:
                return str(split[0])+delimiter+str(split[1]+direction)
            elif len(str(split[1]))==3:
                if direction<0:
                    direction += 1
                return str(split[0])+delimiter+str(int(str(split[1])[:2])+direction)
        return '/'
    
    def AA_trans(residue_name):
        ''' Translate 3 letter residue name to 1 letter name.
        
            @param residue_name: str, 3 letter residue name
        '''
        code_table = {'GLY':'G','ALA':'A','VAL':'V','LEU':'L','ILE':'I',
                      'MET':'M','PHE':'F','TRP':'W','PRO':'P','SER':'S',
                      'THR':'T','CYS':'C','TYR':'Y','ASN':'N','GLN':'Q',
                      'ASP':'D','GLU':'E','LYS':'K','ARG':'R','HIS':'H'}
        if residue_name in code_table:
            residue_name = code_table[residue_name]
        elif len(residue_name)==4 and residue_name[1:] in code_table:
            residue_name = code_table[residue_name[1:]]
        else:
            return '?'
        return residue_name
        
    def extract_AA_from_pdb_line(pdb_line):
        ''' Extracts the 3 letter amino acid name from a line of a pdb file.
            
            @param pdb_line: str, line from pdb file.
        '''
        search = re.search('(ATOM\s+\d+\s+\S+\s*)(\S{3,4})(\s+\S\s*)(-*\d+)([0-9\s+-.]+)(\S)',pdb_line)
        return search.group(2)

    def fetch_lines_from_pdb(self, pdb, preferred_chain, generic_numbers, path='default'):
        ''' Fetches specific lines from pdb file by generic number (if generic number is
            not available then by residue number). Returns nested OrderedDict()
            with generic numbers as keys in the outer dictionary, and atom names as keys
            in the inner dictionary.
            
            @param pdb: Structure or str, 4 letter pdb code \n
            @param preferred_chain: str, preferred chain of structure \n
            @param generic_numbers: list, list of generic numbers to be fetched \n
            @param path: str, path to pdb file
        '''
        if path=='default':
            pdb_array = self.pdb_array_creator('./structure/PDB/'+str(pdb)+'_'+str(preferred_chain)+'_GPCRDB.pdb')
        else:
            pdb_array = self.pdb_array_creator(path+str(pdb)+'_'+str(preferred_chain)+'_GPCRDB.pdb')
        output = OrderedDict()
        for gn in generic_numbers:
            output[gn.replace('x','.')] = pdb_array[gn.replace('x','.')]
        return output

    def pdb_array_creator(self, filename):
        ''' Creates a nested OrderedDict() from a pdb file where residue numbers/generic numbers are 
            keys for the outer OrderedDict(), and atom names are keys for the inner OrderedDict.
            
            @param filename: str, file name with path.
        '''
        with open(filename) as f:
            lines = f.readlines()
        res_num = int(re.search('(ATOM\s+\d+\s+\S+\s*\S{3,4}\s+\S\s*)(-*\d+)([0-9\s+-.]+)(\S)',lines[0]).group(2))
        pdb_array = OrderedDict()
        atom_lines = OrderedDict()
        
        for line in lines:
            res0 = re.compile('(ATOM\s+\d+\s+)(\S+)(\s*\S{{3,4}}\s+\S\s*)({})([0-9\s+-.]+)(\S)'.format(res_num))
            res1 = re.compile('(ATOM\s+\d+\s+)(\S+)(\s*\S{{3,4}}\s+\S\s*)({})([0-9\s+-.]+)(\S)'.format(res_num+1))
            resx = re.compile('(ATOM\s+\d+\s+)(\S+)(\s*\S{3,4}\s+\S\s*)(\d+)([0-9\s+-.]+)(\S)')
            res0_line = res0.match(line)
            res1_line = res1.match(line)
            resx_line = resx.match(line)
            
            if res0_line:
                atom_lines.update({res0_line.group(2):line})
            elif res1_line:
                pdb_array[res_num] = atom_lines
                atom_lines = OrderedDict()
                atom_lines.update({res1_line.group(2):line})
                res_num+=1
            elif resx_line:
                res_num = int(resx_line.group(4))
                atom_lines = OrderedDict()
                atom_lines.update({resx_line.group(2):line})
        pdb_array[res_num] = atom_lines
        
        out_array = OrderedDict()
        for key, value in pdb_array.items():
            res = re.compile('(ATOM\s+\d+\s+)(CA)(\s+)(\S{3})(\s+\S\s*)([0-9\s.-]+)(\d.\d{2}\s+)(-*\d.\d{2})(\s+\S)')
            res = res.match(value['CA'])
                   
            if value['CA'] and res:
                if str(res.group(8))[0]=='-':
                    bulge_gn = str(res.group(8))[1:]+str(1)
                    out_array[bulge_gn] = value
                else:                    
                    out_array[res.group(8)] = value
            else:
                out_array[key] = value
        return out_array
        
class CreateStatistics(object):
    ''' Statistics dictionary for HomologyModeling.
    '''
    def __init__(self, reference):
        self.reference = reference
        self.info_dict = OrderedDict()
    
    def __repr__(self):
        return "<{} \n {} \n>".format(self.reference, self.info_dict)
    
    def add_info(self, info_name, info):
        ''' Adds new information to the statistics dictionary.
        
            @param info_name: str, info name as dictionary key
            @param info: object, any object as value
        '''
        self.info_dict[info_name] = info
        
    
        
        
        