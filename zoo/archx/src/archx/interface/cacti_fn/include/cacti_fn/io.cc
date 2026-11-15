/*------------------------------------------------------------
 *                              CACTI 6.5
 *         Copyright 2008 Hewlett-Packard Development Corporation
 *                         All Rights Reserved
 *
 * Permission to use, copy, and modify this software and its documentation is
 * hereby granted only under the following terms and conditions.  Both the
 * above copyright notice and this permission notice must appear in all copies
 * of the software, derivative works or modified versions, and any portions
 * thereof, and both notices must appear in supporting documentation.
 *
 * Users of this software agree to the terms and conditions set forth herein, and
 * hereby grant back to Hewlett-Packard Company and its affiliated companies ("HP")
 * a non-exclusive, unrestricted, royalty-free right and license under any changes, 
 * enhancements or extensions  made to the core functions of the software, including 
 * but not limited to those affording compatibility with other hardware or software
 * environments, but excluding applications which incorporate this software.
 * Users further agree to use their best efforts to return to HP any such changes,
 * enhancements or extensions that they make and inform HP of noteworthy uses of
 * this software.  Correspondence should be provided to HP at:
 *
 *                       Director of Intellectual Property Licensing
 *                       Office of Strategy and Technology
 *                       Hewlett-Packard Company
 *                       1501 Page Mill Road
 *                       Palo Alto, California  94304
 *
 * This software may be distributed (but not offered for sale or transferred
 * for compensation) to third parties, provided such third parties agree to
 * abide by the terms and conditions of this notice.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND HP DISCLAIMS ALL
 * WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES
 * OF MERCHANTABILITY AND FITNESS.   IN NO EVENT SHALL HP 
 * CORPORATION BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL
 * DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR
 * PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
 * ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS
 * SOFTWARE.
 *------------------------------------------------------------*/

#include <fstream>
#include <iostream>
#include <sstream>
#include <stdlib.h>	// Majid
#include <stdio.h>	// Majid
#ifdef ENABLE_CACHE
#include <db.h>
#endif

#include "io.h"
#include "area.h"
#include "basic_circuit.h"
#include "parameter.h"
#include "Ucache.h"
#include "nuca.h"
#include "crossbar.h"
#include "arbiter.h"
#include "xmlParser.h"	// Majid
#include <cstddef>
#include <cmath>

using namespace std;

InputParameter::InputParameter()
{
	dvs_voltage = std::vector<double>(0);

   // Clear out all data used as the DB key, especially unused bits
   // such that they're zero and not old data that might be different per run
   size_t o1 = offsetof(InputParameter, first);
   size_t o2 = offsetof(InputParameter, last);
   memset((char*)this + o1, 0, o2 - o1);
   is_near_threshold = false;
   use_device_xml = false;
   sram_cell_file[0] = 0;
   data_array_cell_tech_file[0] = 0;
   data_array_peri_tech_file[0] = 0;
   tag_array_cell_tech_file[0] = 0;
   tag_array_peri_tech_file[0] = 0;

}


void select_xml_vdd(InputParameter *ip)
{
  if (!ip->use_device_xml) return;
  XMLNode root = XMLNode::openFileHelper(ip->data_array_cell_tech_file, "device_definition");
  XMLNode levels = root.getChildNode("voltages").getChildNode("vdd");
  const char *super_text = levels.getChildNode("super_threshold").getText(0);
  const char *near_text = levels.getChildNode("near_threshold").getText(0);
  if (!super_text) { cerr << "ERROR: XML device needs a super-threshold voltage." << endl; exit(1); }
  double super_vdd = atof(super_text);
  double near_vdd = near_text ? atof(near_text) : -1;
  if (ip->vdd == 0) ip->vdd = super_vdd;
  for (size_t i = 0; i <= ip->dvs_voltage.size(); ++i) {
    double voltage = i == ip->dvs_voltage.size() ? ip->vdd : ip->dvs_voltage[i];
    if (fabs(voltage - super_vdd) > 1e-6 && (!near_text || fabs(voltage - near_vdd) > 1e-6)) {
      cerr << "ERROR: XML device voltage must be " << super_vdd;
      if (near_text) cerr << " or " << near_vdd;
      cerr << " V; voltage interpolation is not supported." << endl;
      exit(1);
    }
  }
  ip->is_near_threshold = fabs(ip->vdd - super_vdd) > 1e-6;
  ip->vdd = ip->is_near_threshold ? near_vdd : super_vdd;
}

void InputParameter::default_device_files()
{
  F_sz_nm = F_sz_um * 1000;
  if (!use_device_xml) {
    const char *device = 0;
    if (is_finfet && fabs(F_sz_nm - 14) < 1e-6) return;
    if (is_finfet && fabs(F_sz_nm - 7) < 1e-6) device = "xmls/devices/finfet_7nm_std.xml";
    else if (!is_finfet && fabs(F_sz_nm - 14) < 1e-6) device = "xmls/devices/cmos_14nm_std.xml";
    else if (!is_finfet && fabs(F_sz_nm - 22) < 1e-6) device = "xmls/devices/cmos_22nm_hp.xml";
    if (!device) {
      cerr << "ERROR: no device file for " << F_sz_nm << "/" << (is_finfet ? "finfet" : "cmos") << "; pass -device file." << endl;
      exit(1);
    }
    strcpy(data_array_cell_tech_file, device);
    strcpy(data_array_peri_tech_file, device);
    strcpy(tag_array_cell_tech_file, device);
    strcpy(tag_array_peri_tech_file, device);
    use_device_xml = true;
  }
  if (is_ncfet) { cerr << "ERROR: NC-FinFET data exists only for the hardcoded 14 nm path." << endl; exit(1); }
  if (temp < 300 || temp > 400 || temp % 10 != 0) {
    cerr << "ERROR: XML device temperature must be 300 to 400 K in steps of 10 K." << endl;
    exit(1);
  }
  select_xml_vdd(this);
  load_sram_cell_xml();
}

void InputParameter::load_sram_cell_xml()
{
  char temp_var[1000];
  const char *cell_file = sram_cell_file[0] ? sram_cell_file :
    (is_finfet ? "xmls/sram_cells/finfet_sram_6T1.xml" : "xmls/sram_cells/cmos_sram_6T.xml");
	XMLNode SRAM_cell_conf_node = XMLNode::openFileHelper(cell_file,"sram_cell");
	strcpy(temp_var,SRAM_cell_conf_node.getChildNode("type").getText(0));
	if (!strncmp("6T", temp_var, strlen("6T"))) {
		sram_cell_design.setType(std_6T);
	} else if (!strncmp("8T", temp_var, strlen("8T"))) {
		sram_cell_design.setType(std_8T);
	} else {
		cerr << "ERROR: Invalid SRAM cell type!\n";
		exit(0);
	}
	
	if ( !SRAM_cell_conf_node.getChildNode("dual_gate_control").isEmpty() ) {
		if ( SRAM_cell_conf_node.getChildNode("dual_gate_control").nText() == 0 ) {
			cout << "XML ERROR: <dual_gate_control> in the '" << sram_cell_file <<"' file does not have a value.\n";
			cerr << "Please specify either 'true' or 'false' for the dual_gate_control." << endl;
			exit(0);
		} else {
			strcpy(temp_var,SRAM_cell_conf_node.getChildNode("dual_gate_control").getText(0));
			for (int i = 0; temp_var[i]; i++) { temp_var[i] = tolower(temp_var[i]); }
			if (!strncmp("true", temp_var, strlen("true"))) {
				sram_cell_design.setDGcontrol(true);
			} else if (!strncmp("false", temp_var, strlen("false"))) {
				sram_cell_design.setDGcontrol(false);
			} else {
				cerr << "ERROR: Invalid value for the dual_gate_control in '" << sram_cell_file <<"' file!\n";
				exit(0);
			}
		}
	} else {
		sram_cell_design.setDGcontrol(false);
	}
	
	XMLNode SRAM_leak_power = SRAM_cell_conf_node.getChildNode("leakage_power");
	if ( !SRAM_leak_power.getChildNode("bitline").isEmpty() ) {
		if ( SRAM_leak_power.getChildNode("bitline").nText() > 0 ) {
			strcpy(temp_var,SRAM_leak_power.getChildNode("bitline").getText(0));
			double pleak;
			sscanf(temp_var, "%lf", &(pleak));
			sram_cell_design.setPleakAccTx(pleak);
		}
	}
	if ( !SRAM_leak_power.getChildNode("cc_inverters").isEmpty() ) {
		if ( SRAM_leak_power.getChildNode("cc_inverters").nText() > 0 ) {
			strcpy(temp_var,SRAM_leak_power.getChildNode("cc_inverters").getText(0));
			double pleak;
			sscanf(temp_var, "%lf", &(pleak));
			sram_cell_design.setPleakCCInv(pleak);
		}
	}
	
	int Nfins[5] = {0};
	double Lphys[5] = {0}, Ioffs[5] = {0};
	XMLNode SRAM_transistor_parameters = SRAM_cell_conf_node.getChildNode("transistor_parameters");
	if ( is_finfet ) {
		strcpy(temp_var,SRAM_transistor_parameters.getChildNode("acc").getChildNode("num_of_fins").getText(0));
		sscanf(temp_var,"%d",&(Nfins[0]));
		strcpy(temp_var,SRAM_transistor_parameters.getChildNode("pup").getChildNode("num_of_fins").getText(0));
		sscanf(temp_var,"%d",&(Nfins[1]));
		strcpy(temp_var,SRAM_transistor_parameters.getChildNode("pdn").getChildNode("num_of_fins").getText(0));
		sscanf(temp_var,"%d",&(Nfins[2]));
		if (sram_cell_design.getType() == std_8T) {
			strcpy(temp_var,SRAM_transistor_parameters.getChildNode("iso").getChildNode("num_of_fins").getText(0));
			sscanf(temp_var,"%d",&(Nfins[3]));
			strcpy(temp_var,SRAM_transistor_parameters.getChildNode("rac").getChildNode("num_of_fins").getText(0));
			sscanf(temp_var,"%d",&(Nfins[4]));
		}
	} else {
		Nfins[0] = 0; Nfins[1] = 0; Nfins[2] = 0; Nfins[3] = 0; Nfins[4] = 0;
	}
	
	XMLNode SRAM_transistor_definition = XMLNode::openFileHelper(sram_cell_file[0] ? SRAM_transistor_parameters.getChildNode("acc").getChildNode("device_type").getText(0) : data_array_cell_tech_file,"device_definition");
	strcpy(temp_var,SRAM_transistor_definition.getChildNode("geometries").getChildNode("Lphy").getText(0));
	sscanf(temp_var,"%lf",&(Lphys[0]));
	char temperature[10];
	sprintf(temperature,"%d",temp);
	if (is_near_threshold)
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
	else
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
	sscanf(temp_var,"%lf",&(Ioffs[0]));

	SRAM_transistor_definition = XMLNode::openFileHelper(sram_cell_file[0] ? SRAM_transistor_parameters.getChildNode("pup").getChildNode("device_type").getText(0) : data_array_cell_tech_file,"device_definition");
	strcpy(temp_var,SRAM_transistor_definition.getChildNode("geometries").getChildNode("Lphy").getText(0));
	sscanf(temp_var,"%lf",&(Lphys[1]));
	if(is_near_threshold)
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("PMOS").getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
	else
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("PMOS").getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
	sscanf(temp_var,"%lf",&(Ioffs[1]));
	
	SRAM_transistor_definition = XMLNode::openFileHelper(sram_cell_file[0] ? SRAM_transistor_parameters.getChildNode("pdn").getChildNode("device_type").getText(0) : data_array_cell_tech_file,"device_definition");
	strcpy(temp_var,SRAM_transistor_definition.getChildNode("geometries").getChildNode("Lphy").getText(0));
	sscanf(temp_var,"%lf",&(Lphys[2]));
	if(is_near_threshold)
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
	else
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
	sscanf(temp_var,"%lf",&(Ioffs[2]));
	
	if (sram_cell_design.getType() == std_8T) {
		SRAM_transistor_definition = XMLNode::openFileHelper(sram_cell_file[0] ? SRAM_transistor_parameters.getChildNode("iso").getChildNode("device_type").getText(0) : data_array_cell_tech_file,"device_definition");
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("geometries").getChildNode("Lphy").getText(0));
		sscanf(temp_var,"%lf",&(Lphys[3]));
		if (is_near_threshold)
			strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
		else
			strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
		sscanf(temp_var,"%lf",&(Ioffs[3]));

		SRAM_transistor_definition = XMLNode::openFileHelper(sram_cell_file[0] ? SRAM_transistor_parameters.getChildNode("rac").getChildNode("device_type").getText(0) : data_array_cell_tech_file,"device_definition");
		strcpy(temp_var,SRAM_transistor_definition.getChildNode("geometries").getChildNode("Lphy").getText(0));
		sscanf(temp_var,"%lf",&(Lphys[4]));
		if (is_near_threshold)
			strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
		else
			strcpy(temp_var,SRAM_transistor_definition.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS").getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
		sscanf(temp_var,"%lf",&(Ioffs[4]));
	}
	
	for (int i = 0; i < 5; ++i) { this->Nfins[i] = Nfins[i]; this->Lphys[i] = Lphys[i]; }
	sram_cell_design.setTransistorParams(Nfins, Lphys, Ioffs);

}

//Divya modifying parse_cfg() call 14-11-2021
/* Parses "cache.cfg" file */
void InputParameter::parse_cfg(const string & in_file)
{
  FILE *fp = fopen(in_file.c_str(), "r");
  char line[5000];
  char jk[5000];
  char temp_var[5000];
  double Ioffs[5];
  double temp_double;
  char *data = line;
  int offset= 0;


  if(!fp) {
    cout << in_file << " is missing!\n";
    exit(-1);
  }

  while(fscanf(fp, "%[^\n]\n", line) != EOF) {

    if (!strncmp("-device file", line, strlen("-device file"))) {
      if (sscanf(line, "-device file%[^\"]\"%999[^\"]\"", jk, temp_var) != 2) {
        cerr << "ERROR: -device file requires a quoted path." << endl;
        exit(1);
      }
      strcpy(data_array_cell_tech_file, temp_var);
      strcpy(data_array_peri_tech_file, temp_var);
      strcpy(tag_array_cell_tech_file, temp_var);
      strcpy(tag_array_peri_tech_file, temp_var);
      use_device_xml = true;
      continue;
    }
    if (!strncmp("-sram cell file", line, strlen("-sram cell file"))) {
      if (sscanf(line, "-sram cell file%[^\"]\"%999[^\"]\"", jk, sram_cell_file) != 2) {
        cerr << "ERROR: -sram cell file requires a quoted path." << endl;
        exit(1);
      }
      continue;
    }
    if (!strncmp("-transistor type", line, strlen("-transistor type"))) {
      sscanf(line, "-transistor type%[^\"]\"%[^\"]\"", jk, (temp_var));

      if (!strncmp("finfet", temp_var, strlen("finfet"))) {
    	  is_finfet = true;
      }
      else if (!strncmp("cmos", temp_var, strlen("cmos"))) {
    	  is_finfet = false;
      } else {
			cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
			exit(0);
	  }
      continue;
    }

    if (!strncmp("-technology node", line, strlen("-technology node"))) {
      sscanf(line, "-technology node %lf", &(F_sz_um));
      F_sz_nm = F_sz_um*1000;
      continue;
    }

    if (!strncmp("-wire technology node", line, strlen("-wire technology node"))) {
      sscanf(line, "-wire technology node %lf", &(wire_F_sz_um));
      wire_F_sz_nm = wire_F_sz_um*1000;
      continue;
    }

    if (!strncmp("-operating voltage", line, strlen("-operating voltage"))) {
     sscanf(line, "-operating voltage %lf", &(vdd));
      continue;
    }

    if (!strncmp("-DVS(V):", line, strlen("-DVS(V):"))) {
        memmove (line,line+9,strlen(line));
    	while (1 == sscanf(data, "%lf%n", &temp_double, &offset)) {
    		data += offset;
    		dvs_voltage.push_back(temp_double);
    	}
    	continue;
    }

/*
    if(!strncmp("-DVS", line, strlen("-DVS"))) {
      sscanf(line, "-DVS %[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("true", temp_var, strlen("true"))) {
    	  is_dvs = true;
      } else {
    	  is_dvs = false;
      }
//      cout << "DVS : " << is_dvs << endl;
      continue;
    }

    if (!strncmp("-start-limit", line, strlen("-start-limit"))) {
      sscanf(line, "-start-limit %lf", &(dvs_start));
//      cout << "dvs : " << is_dvs << ", start : " << dvs_start;
      continue;
    }
    if (!strncmp("-end-limit", line, strlen("-end-limit"))) {
      sscanf(line, "-end-limit %lf", &(dvs_end));
//      cout << ", end : " << dvs_end << endl;
      continue;
    }
*/
    if (!strncmp("-temperature", line, strlen("-temperature"))) {
       sscanf(line, "-temperature %d", &(temp));
      continue;
    }

    if (!strncmp("-size", line, strlen("-size"))) {
      sscanf(line, "-size %d", &(cache_sz));
      continue;
    }

    if (!strncmp("-block", line, strlen("-block"))) {
      sscanf(line, "-block size %d", &(line_sz));
      continue;
    }

    if (!strncmp("-associativity", line, strlen("-associativity"))) {
      sscanf(line, "-associativity %d", &(assoc));
      continue;
    }

    if(!strncmp("-ncfet", line, strlen("-ncfet"))) {
      sscanf(line, "-ncfet %[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("true", temp_var, strlen("true"))) {
    	  is_ncfet = true;
      } else {
    	  is_ncfet = false;
      }

      //ToDo introducing finfet and ncfet cell types
      //Fixing SRAM cells to 6T1 SRAM model
      sram_cell_design.setType(std_6T);
      Nfins[0] = 1;	// access transistor fins
      Nfins[1] = 1;	// pup fins
      Nfins[2] = 1; 	// pdn fins

      //Dual Gate control is being set to false
      sram_cell_design.setDGcontrol(false);

      if(is_finfet && !use_device_xml && fabs(F_sz_um - 0.014) < 1e-9) {
		  //Fixing the transistor parameters acdng to ncfet/finfet type, instead of reading transistor.xml files
		  if(is_ncfet) {	//for NCFET
			  Lphys[0] = 0.02;	//20-nm access transistor
			  Lphys[1] = 0.02;	//20-nm pup
			  Lphys[2] = 0.02;	//20-nm pdn

			  //NCFET Ioff currents acdng to voltage
			  if(vdd == 0.8) {
				  Ioffs[0] = 5.836957e-10;	//n-type acc transistor
				  Ioffs[1] = 6.39565e-10;	//p-type pup transistor
				  Ioffs[2] = 5.836957e-10;	//n-type pdn transistor
			  } else if(vdd == 0.7) {
				  Ioffs[0] = 6.880435e-10;	//n-type acc transistor
				  Ioffs[1] = 7.836957e-10;	//p-type pup transistor
				  Ioffs[2] = 6.880435e-10;	//n-type pdn transistor
			  } else if(vdd == 0.6) {
				  Ioffs[0] = 8.119565e-10;	//n-type acc transistor
				  Ioffs[1] = 1.0e-09;		//p-type pup transistor
				  Ioffs[2] = 8.119565e-10;	//n-type pdn transistor
			  } else if(vdd == 0.5) {
				  Ioffs[0] = 1.0e-09;		//n-type acc transistor
				  Ioffs[1] = 1.184783e-09;	//p-type pup transistor
				  Ioffs[2] = 1.0e-09;		//n-type pdn transistor
			  } else if(vdd == 0.4) {
				  Ioffs[0] = 1.119565e-09;	//n-type acc transistor
				  Ioffs[1] = 1.456522e-09;	//p-type pup transistor
				  Ioffs[2] = 1.119565e-09;	//n-type pdn transistor
			  } else if(vdd == 0.3) {
				  Ioffs[0] = 1.304348e-09;	//n-type acc transistor
				  Ioffs[1] = 1.771739e-09;	//p-type pup transistor
				  Ioffs[2] = 1.304348e-09;	//n-type pdn transistor
			  } else if(vdd == 0.2) {
				  Ioffs[0] = 1.51087e-09;	//n-type acc transistor
				  Ioffs[1] = 2.163043e-09;	//p-type pup transistor
				  Ioffs[2] = 1.51087e-09;	//n-type pdn transistor
			  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
		  }
		  else {	//for FinFET
			  Lphys[0] = 0.02;	//20-nm access transistor
			  Lphys[1] = 0.02;	//20-nm pup
			  Lphys[2] = 0.02;	//20-nm pdn

			  //FinFET Ioff currents acdng to voltage
			  if(vdd == 0.8) {
				  Ioffs[0] = 6.684783e-09;	//n-type acc transistor
				  Ioffs[1] = 6.478261e-09;	//p-type pup transistor
				  Ioffs[2] = 6.684783e-09;	//n-type pdn transistor
			  } else if(vdd == 0.7) {
				  Ioffs[0] = 5.336957e-09;	//n-type acc transistor
				  Ioffs[1] = 5.130435e-09;	//p-type pup transistor
				  Ioffs[2] = 5.336957e-09;	//n-type pdn transistor
			  } else if(vdd == 0.6) {
				  Ioffs[0] = 4.217391e-09;	//n-type acc transistor
				  Ioffs[1] = 4.054348e-09;	//p-type pup transistor
				  Ioffs[2] = 4.217391e-09;	//n-type pdn transistor
			  } else if(vdd == 0.5) {
				  Ioffs[0] = 3.304348e-09;		//n-type acc transistor
				  Ioffs[1] = 3.195652e-09;	//p-type pup transistor
				  Ioffs[2] = 3.304348e-09;		//n-type pdn transistor
			  } else if(vdd == 0.4) {
				  Ioffs[0] = 2.565217e-09;	//n-type acc transistor
				  Ioffs[1] = 2.5e-09;	//p-type pup transistor
				  Ioffs[2] = 2.565217e-09;	//n-type pdn transistor
			  } else if(vdd == 0.3) {
				  Ioffs[0] = 2.0e-09;	//n-type acc transistor
				  Ioffs[1] = 2.0e-09;	//p-type pup transistor
				  Ioffs[2] = 2.0e-09;	//n-type pdn transistor
			  } else if(vdd == 0.2) {
				  Ioffs[0] = 1.489133e-09;	//n-type acc transistor
				  Ioffs[1] = 1.532609e-09;	//p-type pup transistor
				  Ioffs[2] = 1.489133e-09;	//n-type pdn transistor
			  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
		  }
		  sram_cell_design.setTransistorParams(Nfins, Lphys, Ioffs);
      }
      continue;
    }

    if (!strncmp("-read-write", line, strlen("-read-write"))) {
      sscanf(line, "-read-write port %d", &(num_rw_ports));
      continue;
    }

    if (!strncmp("-exclusive read", line, strlen("exclusive read"))) {
      sscanf(line, "-exclusive read port %d", &(num_rd_ports));
      continue;
    }

    if(!strncmp("-exclusive write", line, strlen("-exclusive write"))) {
      sscanf(line, "-exclusive write port %d", &(num_wr_ports));
      continue;
    }

    if (!strncmp("-single ended", line, strlen("-single ended"))) {
      sscanf(line, "-single %[(:-~)*]%d", jk,
          &(num_se_rd_ports));
      continue;
    }

    if (!strncmp("-search", line, strlen("-search"))) {
      sscanf(line, "-search port %d", &(num_search_ports));
      continue;
    }

    if(!strncmp("-cache model", line, strlen("-cache model"))) {
      sscanf(line, "-cache model %[^\"]\"%[^\"]\"", jk, temp_var);

      if (!strncmp("UCA", temp_var, strlen("UCA"))) {
        nuca = 0;
      }
      else {
        nuca = 1;
      }
      continue;
    }

    if (!strncmp("-uca bank", line, strlen("-uca bank"))) {
      sscanf(line, "-uca bank%[((:-~)| )*]%d", jk, &(nbanks));
      continue;
    }

    if(!strncmp("-nuca bank", line, strlen("-nuca bank"))) {
      sscanf(line, "-nuca bank count %d", &(nuca_bank_count));

      if (nuca_bank_count != 0) {
        force_nuca_bank = 1;
      }
      continue;
    }

    if (!strncmp("-bus width", line, strlen("-bus width"))) {
      sscanf(line, "-bus width %d", &(out_w));
//      cout << "out_w : " << out_w << " buswidth : " << line << endl;
      continue;
    }

    if (!strncmp("-memory type", line, strlen("-memory type"))) {
      sscanf(line, "-memory type%[^\"]\"%[^\"]\"", jk, temp_var);

      if (!strncmp("cache", temp_var, sizeof("cache"))) {
        is_cache = true;
      }
      else
      {
        is_cache = false;
      }

      if (!strncmp("main memory", temp_var, sizeof("main memory"))) {
        is_main_mem = true;
      }
      else {
        is_main_mem = false;
      }

      if (!strncmp("cam", temp_var, sizeof("cam"))) {
        pure_cam = true;
      }
      else {
        pure_cam = false;
      }

      if (!strncmp("ram", temp_var, sizeof("ram"))) {
        pure_ram = true;
      }
      else {
    	  if (!is_main_mem)
    		  pure_ram = false;
    	  else
    		  pure_ram = true;
      }
      continue;
    }

    if (!strncmp("-tag size", line, strlen("-tag size"))) {
      sscanf(line, "-tag size%[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("default", temp_var, sizeof("default"))) {
        specific_tag = false;
        tag_w = 42; /* the actual value is calculated
                     * later based on the cache size, bank count, and associativity
                     */
      }
      else {
        specific_tag = true;
        sscanf(line, "-tag size %d", &(tag_w));
//        cout << "tag : " << tag_w << endl;
      }
      continue;
    }

    if (!strncmp("-access mode", line, strlen("-access mode"))) {
      sscanf(line, "-access %[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("fast", temp_var, strlen("fast"))) {
        access_mode = 2;
      } else if (!strncmp("sequential", temp_var, strlen("sequential"))) {
        access_mode = 1;
      } else if(!strncmp("normal", temp_var, strlen("normal"))) {
        access_mode = 0;
      } else {
        cout << "ERROR: Invalid access mode!\n";
        exit(0);
      }
      continue;
    }

    if(!strncmp("-optimize", line, strlen("-optimize"))) {
      sscanf(line, "-optimize  %[^\"]\"%[^\"]\"", jk, temp_var);

      if(!strncmp("ED^2", temp_var, strlen("ED^2"))) {
        ed = 2;
      }
      else if(!strncmp("ED", temp_var, strlen("ED"))) {
        ed = 1;
      }
      else {
        ed = 0;
      }
    }

    if(!strncmp("-design", line, strlen("-design"))) {
      sscanf(line, "-%[((:-~)| |,)*]%d:%d:%d:%d:%d", jk,
          &(delay_wt), &(dynamic_power_wt),
          &(leakage_power_wt),
          &(cycle_time_wt), &(area_wt));
      continue;
    }

    if(!strncmp("-deviate", line, strlen("-deviate"))) {
      sscanf(line, "-%[((:-~)| |,)*]%d:%d:%d:%d:%d", jk,
          &(delay_dev), &(dynamic_power_dev),
          &(leakage_power_dev),
          &(cycle_time_dev), &(area_dev));
      continue;
    }

    if(!strncmp("-NUCAdesign", line, strlen("-NUCAdesign"))) {
      sscanf(line, "-%[((:-~)| |,)*]%d:%d:%d:%d:%d", jk,
          &(delay_wt_nuca), &(dynamic_power_wt_nuca),
          &(leakage_power_wt_nuca),
          &(cycle_time_wt_nuca), &(area_wt_nuca));
      continue;
    }

    if(!strncmp("-NUCAdeviate", line, strlen("-NUCAdeviate"))) {
      sscanf(line, "-%[((:-~)| |,)*]%d:%d:%d:%d:%d", jk,
          &(delay_dev_nuca), &(dynamic_power_dev_nuca),
          &(leakage_power_dev_nuca),
          &(cycle_time_dev_nuca), &(area_dev_nuca));
      continue;
    }

    if(!strncmp("-interconnects", line, strlen("-interconnects"))) {
        sscanf(line, "-interconnects  %[^\"]\"%[^\"]\"", jk, temp_var);
    	if (!strncmp("ITRS2012", temp_var, strlen("ITRS2012"))) {
    		is_itrs2012 = true;
    		is_asap7 = false;
    	} else if (!strncmp("RonHo2003", temp_var, strlen("RonHo2003"))) {
    		is_itrs2012 = false;
    		is_asap7 = false;
    	} else if (!strncmp("ASAP7", temp_var, strlen("ASAP7"))) {
    		is_asap7 = true;
    		is_itrs2012 = false;
    	}else {
    		cout << "ERROR: Invalid interconnect source!\n";
    		exit(0);
    	}
    	continue;
    }

    if(!strncmp("-wire signalling", line, strlen("-wire signalling"))) {
      sscanf(line, "-wire%[^\"]\"%[^\"]\"", jk, temp_var);

      if (!strncmp("default", temp_var, strlen("default"))) {
        force_wiretype = 0;
        wt = Global;
      }
      else if (!(strncmp("Global_10", temp_var, strlen("Global_10")))) {
        force_wiretype = 1;
        wt = Global_10;
      }
      else if (!(strncmp("Global_20", temp_var, strlen("Global_20")))) {
        force_wiretype = 1;
        wt = Global_20;
      }
      else if (!(strncmp("Global_30", temp_var, strlen("Global_30")))) {
        force_wiretype = 1;
        wt = Global_30;
      }
      else if (!(strncmp("Global_5", temp_var, strlen("Global_5")))) {
        force_wiretype = 1;
        wt = Global_5;
      }
      else if (!(strncmp("Global", temp_var, strlen("Global")))) {
        force_wiretype = 1;
        wt = Global;
      }
      else {
        wt = Low_swing;
        force_wiretype = 1;
      }
      continue;
    }

    if(!strncmp("-Wire inside mat", line, strlen("-Wire inside mat"))) {
      sscanf(line, "-Wire%[^\"]\"%[^\"]\"", jk, temp_var);

      if (!strncmp("global", temp_var, strlen("global"))) {
        wire_is_mat_type = 2;
        continue;
      }
      else if (!strncmp("local", temp_var, strlen("local"))) {
        wire_is_mat_type = 0;
        continue;
      }
      else {
        wire_is_mat_type = 1;
        continue;
      }
    }

    if(!strncmp("-Wire outside mat", line, strlen("-Wire outside mat"))) {
      sscanf(line, "-Wire%[^\"]\"%[^\"]\"", jk, temp_var);

      if (!strncmp("global", temp_var, strlen("global"))) {
        wire_os_mat_type = 2;
      }
      else {
        wire_os_mat_type = 1;
      }
      continue;
    }

    if(!strncmp("-Interconnect projection", line, strlen("-Interconnect projection"))) {
      sscanf(line, "-Interconnect projection%[^\"]\"%[^\"]\"", jk, temp_var);

      if (!strncmp("aggressive", temp_var, strlen("aggressive"))) {
        ic_proj_type = 0;
      }
      else {
        ic_proj_type = 1;
      }
      continue;
    }

    if(!strncmp("-Core", line, strlen("-Core"))) {
      sscanf(line, "-Core count %d\n", &(cores));
      if (cores > 16) {
        printf("No. of cores should be less than 16!\n");
      }
      continue;
    }

    if(!strncmp("-Cache level", line, strlen("-Cache level"))) {
      sscanf(line, "-Cache l%[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("L2", temp_var, strlen("L2"))) {
        cache_level = 0;
      }
      else {
        cache_level = 1;
      }
      continue;
    }

    if(!strncmp("-Add ECC", line, strlen("-Add ECC"))) {
      sscanf(line, "-Add ECC %[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("true", temp_var, strlen("true"))) {
        add_ecc_b_ = true;
      }
      else {
        add_ecc_b_ = false;
      }
      continue;
    }

    if(!strncmp("-Print level", line, strlen("-Print level"))) {
      sscanf(line, "-Print l%[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("DETAILED", temp_var, strlen("DETAILED"))) {
        print_detail = 1;
      }
      else {
        print_detail = 0;
      }
      continue;
    }

    if(!strncmp("-Print input parameters", line, strlen("-Print input parameters"))) {
      sscanf(line, "-Print input %[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("true", temp_var, strlen("true"))) {
        print_input_args = true;
      }
      else {
        print_input_args = false;
      }
    }

    if(!strncmp("-Force cache config", line, strlen("-Force cache config"))) {
      sscanf(line, "-Force cache %[^\"]\"%[^\"]\"", jk, temp_var);
      if (!strncmp("true", temp_var, strlen("true"))) {
        force_cache_config = true;
      }
      else {
        force_cache_config = false;
      }
    }

    if(!strncmp("-Ndbl", line, strlen("-Ndbl"))) {
      sscanf(line, "-Ndbl %d\n", &(ndbl));
      continue;
    }
    if(!strncmp("-Ndwl", line, strlen("-Ndwl"))) {
      sscanf(line, "-Ndwl %d\n", &(ndwl));
      continue;
    }
    if(!strncmp("-Nspd", line, strlen("-Nspd"))) {
      sscanf(line, "-Nspd %d\n", &(nspd));
      continue;
    }
    if(!strncmp("-Ndsam1", line, strlen("-Ndsam1"))) {
      sscanf(line, "-Ndsam1 %d\n", &(ndsam1));
      continue;
    }
    if(!strncmp("-Ndsam2", line, strlen("-Ndsam2"))) {
      sscanf(line, "-Ndsam2 %d\n", &(ndsam2));
      continue;
    }
    if(!strncmp("-Ndcm", line, strlen("-Ndcm"))) {
		  sscanf(line, "-Ndcm %d\n", &(ndcm));
		  continue;
		}

	   if(!strncmp("-Ntbl", line, strlen("-Ntbl"))) {
		 sscanf(line, "-Ntbl %d\n", &(ntbl));
		 continue;
	   }
	   if(!strncmp("-Ntwl", line, strlen("-Ntwl"))) {
		 sscanf(line, "-Ntwl %d\n", &(ntwl));
		 continue;
	   }
	   if(!strncmp("-Ntspd", line, strlen("-Ntspd"))) {
		 sscanf(line, "-Ntspd %d\n", &(ntspd));
		 continue;
	   }
	   if(!strncmp("-Ntsam1", line, strlen("-Ntsam1"))) {
		 sscanf(line, "-Ntsam1 %d\n", &(ntsam1));
		 continue;
	   }
	   if(!strncmp("-Ntsam2", line, strlen("-Ntsam2"))) {
		 sscanf(line, "-Ntsam2 %d\n", &(ntsam2));
		 continue;
	   }
	  if(!strncmp("-Ntcm", line, strlen("-Ntcm"))) {
		 sscanf(line, "-Ntcm %d\n", &(ntcm));
		 continue;
	  }

	  if (!strncmp("-page size", line, strlen("-page size"))) {
		sscanf(line, "-page size %[(:-~)*]%u", jk, &(page_sz_bits));
		continue;
	  }

	  if (!strncmp("-burst length", line, strlen("-burst length"))) {
		sscanf(line, "-burst %[(:-~)*]%u", jk, &(burst_len));
		continue;
	  }

	  if (!strncmp("-internal prefetch width", line, strlen("-internal prefetch width"))) {
		sscanf(line, "-internal prefetch %[(:-~)*]%u", jk, &(int_prefetch_w));
		continue;
	  }
  }
	data_arr_ram_cell_tech_type = 0;
	data_arr_peri_global_tech_type = 0;
	tag_arr_ram_cell_tech_type = 0;
	tag_arr_peri_global_tech_type = 0;


  rpters_in_htree = true;
  fclose(fp);
  default_device_files();
}
//divya end

void InputParameter::display_ip()
{
  cout << "\n----------------------------------------"; // Alireza
  cout << "\n            Input Parameters            "; // Alireza
  cout << "\n----------------------------------------" << endl; // Alireza
  cout << "Cache size                    : " << cache_sz << "B" << endl; // unit. -Alireza
  cout << "Block size                    : " << line_sz  << "B" << endl; // unit. -Alireza
  cout << "Associativity                 : " << assoc << endl;
  cout << "Read only ports               : " << num_rd_ports << endl;
  cout << "Write only ports              : " << num_wr_ports << endl;
  cout << "Read write ports              : " << num_rw_ports << endl;
  cout << "Single ended read ports       : " << num_se_rd_ports << endl;
  if (fully_assoc||pure_cam)
  {
	  cout << "Search ports                  : " << num_search_ports << endl;
  }
  cout << "Cache banks (UCA)             : " << nbanks << endl;
  cout << "Technology                    : " << F_sz_nm << "nm" << endl; // changed to nm. -Alireza
  cout << "Transistor type               : " << (is_finfet ? "FinFET" : "CMOS" ) << endl; // Alireza
  if(is_finfet)
	  cout << "NCFET (1) or FinFET (0): " << is_ncfet << endl;
//  cout << "Operating voltage             : " << (is_near_threshold ? "Near-threshold" : "Super-threshold" ) << endl; // Alireza
    cout << "Operating voltage             : " << vdd << endl; // Alireza
/* 	if (g_ip->sram_cell_design.getType()==std_6T) { // Alireza
    cout << "SRAM cell type                : " << "Standard 6T" << endl;
  } else if (g_ip->sram_cell_design.getType()==std_8T) {
    cout << "SRAM cell type                : " << "Standard 8T" << endl;
  }
*/
    cout << "Temperature                   : " << temp << "K" << endl; // Alireza
  cout << "Tag size                      : " << tag_w << endl;
  if (is_cache) {
    cout << "cache type                    : " << "Cache" << endl;
  }
  if (is_main_mem) {
    cout << "cache type                    : " << "Main Memory" << endl; // Alireza
  }
  if(pure_ram){ // Alireza
    cout << "cache type                    : " << "Scratch RAM" << endl;
  }
  if(pure_cam)  {
      cout << "array type                    : " << "CAM" << endl;
  }
  //cout << "Model as memory               : " << is_main_mem << endl;  // Alireza
  cout << "Access mode                   : " << access_mode << endl;
  cout << "Data array cell type          : " << data_arr_ram_cell_tech_type << endl;
  cout << "Data array peripheral type    : " << data_arr_peri_global_tech_type << endl;
  cout << "Tag array cell type           : " << tag_arr_ram_cell_tech_type << endl;
  cout << "Tag array peripheral type     : " << tag_arr_peri_global_tech_type << endl;
  cout << "Design objective (UCA wt)     : " << delay_wt << " "
                                                << dynamic_power_wt << " " << leakage_power_wt << " " << cycle_time_wt
                                                << " " << area_wt << endl;
  cout << "Design objective (UCA dev)    : " << delay_dev << " "
                                                << dynamic_power_dev << " " << leakage_power_dev << " " << cycle_time_dev
                                                << " " << area_dev << endl;
  cout << "Design objective (NUCA wt)    : " << delay_wt_nuca << " "
                                                << dynamic_power_wt_nuca << " " << leakage_power_wt_nuca << " " << cycle_time_wt_nuca
                                                << " " << area_wt_nuca << endl;
  cout << "Design objective (NUCA dev)   : " << delay_dev_nuca << " "
                                                << dynamic_power_dev_nuca << " " << leakage_power_dev_nuca << " " << cycle_time_dev_nuca
                                                << " " << area_dev_nuca << endl;
  cout << "Cache model                   : " << (nuca ? "NUCA" : "UCA" ) << endl; // Alireza
  cout << "Nuca bank                     : " << nuca_bank_count << endl;
  cout << "Wire inside mat               : " << wire_is_mat_type << endl;
  cout << "Wire outside mat              : " << wire_os_mat_type << endl;
  cout << "Interconnect projection       : " << ic_proj_type << endl;
  cout << "Wire signalling               : " << wt << endl;
  cout << "Force Wire type				 : " << force_wiretype << endl;
  cout << "Cores                         : " << cores << endl;
  cout << "Print details                 : " << (print_detail ? "Yes" : "No" ) << endl; // Alireza
  cout << "ECC overhead                  : " << (add_ecc_b_ ? "Yes" : "No" ) << endl; // Alireza
  cout << "Page size                     : " << page_sz_bits << endl;
  cout << "Burst length                  : " << burst_len << endl;
  cout << "Internal prefetch width       : " << int_prefetch_w << endl;
  cout << "Force cache config            : " << (g_ip->force_cache_config ? "Yes" : "No" ) << endl; // Alireza
  cout << "Optimization Goal			 : " << g_ip->ed << endl;
  if (g_ip->force_cache_config) {
    cout << "Ndwl                          : " << g_ip->ndwl << endl;
    cout << "Ndbl                          : " << g_ip->ndbl << endl;
    cout << "Nspd                          : " << g_ip->nspd << endl;
    cout << "Ndcm                          : " << g_ip->ndcm << endl;
    cout << "Ndsam1                        : " << g_ip->ndsam1 << endl;
    cout << "Ndsam2                        : " << g_ip->ndsam2 << endl;
  }
  cout << "Bus width			: " << g_ip->out_w << endl;
}

powerComponents operator+(const powerComponents & x, const powerComponents & y)
{
  powerComponents z;

  z.dynamic = x.dynamic + y.dynamic;
  z.leakage = x.leakage + y.leakage;

  return z;
}

powerComponents operator*(const powerComponents & x, double const * const y)
{
  powerComponents z;

  z.dynamic = x.dynamic*y[0];
  z.leakage = x.leakage*y[1];

  return z;
}

powerDef operator+(const powerDef & x, const powerDef & y)
{
  powerDef z;

  z.readOp  = x.readOp  + y.readOp;
  z.writeOp = x.writeOp + y.writeOp;
  z.searchOp = x.searchOp + y.searchOp;

  return z;
}

powerDef operator*(const powerDef & x, double const * const y)
{
  powerDef z;

  z.readOp   = x.readOp*y;
  z.writeOp  = x.writeOp*y;
  z.searchOp = x.searchOp*y;
  return z;
}


uca_org_t cacti_interface(const string & infile_name)
{
  uca_org_t fin_res;
  fin_res.valid = false;

  g_ip = new InputParameter();
  g_ip->parse_cfg(infile_name);
//  cout << "parsing file done \n" ;

  if (g_ip->error_checking() == false) { cout << "ERROR: Invalid input parameters!\n", exit(0); }
  if (g_ip->print_input_args)
	  g_ip->display_ip();

//  init_tech_params(g_ip->F_sz_um, false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //Divya added wire_technology
//  cout << "tech params done \n" ;

  if (g_ip->print_input_args) g_tp.display(); // Alireza
  
  Wire winit; // Do not delete this line. It initializes wires.
  
  if (g_ip->nuca == 1)
  {
    Nuca n(&g_tp.peri_global);
    n.sim_nuca();
  }
//  g_ip->display_ip();
//  cout << "entering solve \n" ;
  solve(&fin_res);
  Wire wprint;//reset wires to original configuration as in *.cfg file (dvs level 0)

  //Divya begin
//  if (g_ip->is_dvs)
  if (!g_ip->dvs_voltage.empty())
   {
 	  update_dvs(&fin_res);
   }
  //Divya end

  output_UCA(&fin_res);
  //output_summary_of_results(&fin_res);
  output_summary_of_results_file(&fin_res);

//  Wire wprint;//reset wires to original configuration as in *.cfg file (dvs level 0)
  //Wire::print_wire();
  wprint.print_wire();

  delete (g_ip);
  return fin_res;
}


uca_org_t cacti_interface(
    int cache_size,
    int line_size,
    int associativity,
    int rw_ports,
    int excl_read_ports,
    int excl_write_ports,
    int single_ended_read_ports,
    int banks,
    double tech_node, // in nm
    int page_sz,
    int burst_length,
    int pre_width,
    int output_width,
    int specific_tag,
    int tag_width,
    int access_mode, //0 normal, 1 seq, 2 fast
    int cache, //scratch ram or cache
    int main_mem,
    int obj_func_delay,
    int obj_func_dynamic_power,
    int obj_func_leakage_power,
    int obj_func_area,
    int obj_func_cycle_time,
    int dev_func_delay,
    int dev_func_dynamic_power,
    int dev_func_leakage_power,
    int dev_func_area,
    int dev_func_cycle_time,
    int ed_ed2_none, // 0 - ED, 1 - ED^2, 2 - use weight and deviate
    int temp,
    int wt, //0 - default(search across everything), 1 - global, 2 - 5% delay penalty, 3 - 10%, 4 - 20 %, 5 - 30%, 6 - low-swing 
    int data_arr_ram_cell_tech_flavor_in, // 0-4
    int data_arr_peri_global_tech_flavor_in, 
    int tag_arr_ram_cell_tech_flavor_in,
    int tag_arr_peri_global_tech_flavor_in,
    int interconnect_projection_type_in, // 0 - aggressive, 1 - normal
    int wire_inside_mat_type_in, 
    int wire_outside_mat_type_in, 
    int is_nuca, // 0 - UCA, 1 - NUCA
    int core_count,
    int cache_level, // 0 - L2, 1 - L3
    int nuca_bank_count,
    int nuca_obj_func_delay,
    int nuca_obj_func_dynamic_power,
    int nuca_obj_func_leakage_power,
    int nuca_obj_func_area,
    int nuca_obj_func_cycle_time,
    int nuca_dev_func_delay,
    int nuca_dev_func_dynamic_power,
    int nuca_dev_func_leakage_power,
    int nuca_dev_func_area,
    int nuca_dev_func_cycle_time,
    int REPEATERS_IN_HTREE_SEGMENTS_in,//TODO for now only wires with repeaters are supported
    int p_input) 
{
  g_ip = new InputParameter();
  g_ip->add_ecc_b_ = true;

  g_ip->data_arr_ram_cell_tech_type    = data_arr_ram_cell_tech_flavor_in;
  g_ip->data_arr_peri_global_tech_type = data_arr_peri_global_tech_flavor_in;
  g_ip->tag_arr_ram_cell_tech_type     = tag_arr_ram_cell_tech_flavor_in;
  g_ip->tag_arr_peri_global_tech_type  = tag_arr_peri_global_tech_flavor_in;

  g_ip->ic_proj_type     = interconnect_projection_type_in;
  g_ip->wire_is_mat_type = wire_inside_mat_type_in;
  g_ip->wire_os_mat_type = wire_outside_mat_type_in;
  g_ip->burst_len        = burst_length;
  g_ip->int_prefetch_w   = pre_width;
  g_ip->page_sz_bits     = page_sz;

  g_ip->cache_sz            = cache_size;
  g_ip->line_sz             = line_size;
  g_ip->assoc               = associativity;
  g_ip->nbanks              = banks;
  g_ip->out_w               = output_width;
  g_ip->specific_tag        = specific_tag;
  if (tag_width == 0) {
    g_ip->tag_w = 42; 
  }
  else {
    g_ip->tag_w               = tag_width;
  }

  g_ip->access_mode         = access_mode;
  g_ip->delay_wt = obj_func_delay;
  g_ip->dynamic_power_wt = obj_func_dynamic_power;
  g_ip->leakage_power_wt = obj_func_leakage_power;
  g_ip->area_wt = obj_func_area;
  g_ip->cycle_time_wt    = obj_func_cycle_time;
  g_ip->delay_dev = dev_func_delay;
  g_ip->dynamic_power_dev = dev_func_dynamic_power;
  g_ip->leakage_power_dev = dev_func_leakage_power;
  g_ip->area_dev = dev_func_area;
  g_ip->cycle_time_dev    = dev_func_cycle_time;
  g_ip->ed = ed_ed2_none;

  switch(wt) {
    case (0):
      g_ip->force_wiretype = 0;
      g_ip->wt = Global;
      break;
    case (1):
      g_ip->force_wiretype = 1;
      g_ip->wt = Global;
      break;
    case (2):
      g_ip->force_wiretype = 1;
      g_ip->wt = Global_5;
      break;
    case (3):
      g_ip->force_wiretype = 1;
      g_ip->wt = Global_10;
      break;
    case (4):
      g_ip->force_wiretype = 1;
      g_ip->wt = Global_20;
      break;
    case (5):
      g_ip->force_wiretype = 1;
      g_ip->wt = Global_30;
      break;
    case (6):
      g_ip->force_wiretype = 1;
      g_ip->wt = Low_swing;
      break;
    default:
      cout << "Unknown wire type!\n";
      exit(0);
  }

  g_ip->delay_wt_nuca = nuca_obj_func_delay;
  g_ip->dynamic_power_wt_nuca = nuca_obj_func_dynamic_power;
  g_ip->leakage_power_wt_nuca = nuca_obj_func_leakage_power;
  g_ip->area_wt_nuca = nuca_obj_func_area;
  g_ip->cycle_time_wt_nuca    = nuca_obj_func_cycle_time;
  g_ip->delay_dev_nuca = dev_func_delay;
  g_ip->dynamic_power_dev_nuca = nuca_dev_func_dynamic_power;
  g_ip->leakage_power_dev_nuca = nuca_dev_func_leakage_power;
  g_ip->area_dev_nuca = nuca_dev_func_area;
  g_ip->cycle_time_dev_nuca    = nuca_dev_func_cycle_time;
  g_ip->nuca = is_nuca;
  g_ip->nuca_bank_count = nuca_bank_count;
  if(nuca_bank_count > 0) {
    g_ip->force_nuca_bank = 1;
  }
  g_ip->cores = core_count;
  g_ip->cache_level = cache_level;

  g_ip->temp = temp;

  g_ip->F_sz_nm         = tech_node;
  g_ip->F_sz_um         = tech_node / 1000;
  g_ip->default_device_files();
  g_ip->is_main_mem     = (main_mem != 0) ? true : false;
  g_ip->is_cache        = (cache != 0) ? true : false;
  g_ip->rpters_in_htree = (REPEATERS_IN_HTREE_SEGMENTS_in != 0) ? true : false;

  g_ip->num_rw_ports    = rw_ports;
  g_ip->num_rd_ports    = excl_read_ports;
  g_ip->num_wr_ports    = excl_write_ports;
  g_ip->num_se_rd_ports = single_ended_read_ports;
  g_ip->print_detail = 1;
  g_ip->nuca = 0;

  g_ip->wt = Global_5;
  g_ip->force_cache_config = false;
  g_ip->force_wiretype = false;
  g_ip->print_input_args = p_input;


  uca_org_t fin_res;
  fin_res.valid = false;

  if (g_ip->error_checking() == false) exit(0);
  if (g_ip->print_input_args) 
    g_ip->display_ip();
//  init_tech_params(g_ip->F_sz_um, false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //divya added wire technology

  Wire winit; // Do not delete this line. It initializes wires.

  if (g_ip->nuca == 1)
  {
    Nuca n(&g_tp.peri_global);
    n.sim_nuca();
  }
  solve(&fin_res);

  output_UCA(&fin_res);
  //output_summary_of_results(&fin_res);

  delete (g_ip);
  return fin_res;
}

//divya added 14-11-2021
//McPAT's plain interface by parameter passing, please keep !!!
uca_org_t cacti_interface(
    int cache_size,
    int line_size,
    int associativity,
    int rw_ports,
    int excl_read_ports,// para5
    int excl_write_ports,
    int single_ended_read_ports,
    int search_ports,
    int banks,
    double tech_node,//para10
    int output_width,
    int specific_tag,
    int tag_width,
    int access_mode,
    int cache,      //para15
    int main_mem,
    int obj_func_delay,
    int obj_func_dynamic_power,
    int obj_func_leakage_power,
    int obj_func_cycle_time, //para20
    int obj_func_area,
    int dev_func_delay,
    int dev_func_dynamic_power,
    int dev_func_leakage_power,
    int dev_func_area, //para25
    int dev_func_cycle_time,
    int ed_ed2_none, // 0 - ED, 1 - ED^2, 2 - use weight and deviate
    int temp,
    int wt, //0 - default(search across everything), 1 - global, 2 - 5% delay penalty, 3 - 10%, 4 - 20 %, 5 - 30%, 6 - low-swing
    int data_arr_ram_cell_tech_flavor_in,//para30
    int data_arr_peri_global_tech_flavor_in,
    int tag_arr_ram_cell_tech_flavor_in,
    int tag_arr_peri_global_tech_flavor_in,
    int interconnect_projection_type_in,
    int wire_inside_mat_type_in,//para35
    int wire_outside_mat_type_in,
    int REPEATERS_IN_HTREE_SEGMENTS_in,
    int VERTICAL_HTREE_WIRES_OVER_THE_ARRAY_in,
    int BROADCAST_ADDR_DATAIN_OVER_VERTICAL_HTREES_in,
    int PAGE_SIZE_BITS_in,//para40
    int BURST_LENGTH_in,
    int INTERNAL_PREFETCH_WIDTH_in,
    int force_wiretype,
    int wiretype,
    int force_config,//para45
    int ndwl,
    int ndbl,
    int nspd,
    int ndcm,
    int ndsam1,//para50
    int ndsam2,
    int ecc)
{
  g_ip = new InputParameter();

  uca_org_t fin_res;
  fin_res.valid = false;

  g_ip->data_arr_ram_cell_tech_type    = data_arr_ram_cell_tech_flavor_in;
  g_ip->data_arr_peri_global_tech_type = data_arr_peri_global_tech_flavor_in;
  g_ip->tag_arr_ram_cell_tech_type     = tag_arr_ram_cell_tech_flavor_in;
  g_ip->tag_arr_peri_global_tech_type  = tag_arr_peri_global_tech_flavor_in;

  g_ip->ic_proj_type     = interconnect_projection_type_in;
  g_ip->wire_is_mat_type = wire_inside_mat_type_in;
  g_ip->wire_os_mat_type = wire_outside_mat_type_in;
  g_ip->burst_len        = BURST_LENGTH_in;
  g_ip->int_prefetch_w   = INTERNAL_PREFETCH_WIDTH_in;
  g_ip->page_sz_bits     = PAGE_SIZE_BITS_in;

  g_ip->cache_sz            = cache_size;
  g_ip->line_sz             = line_size;
  g_ip->assoc               = associativity;
  g_ip->nbanks              = banks;
  g_ip->out_w               = output_width;
  g_ip->specific_tag        = specific_tag;
  if (specific_tag == 0) {
    g_ip->tag_w = 42;
  }
  else {
    g_ip->tag_w               = tag_width;
  }

  g_ip->access_mode         = access_mode;
  g_ip->delay_wt = obj_func_delay;
  g_ip->dynamic_power_wt = obj_func_dynamic_power;
  g_ip->leakage_power_wt = obj_func_leakage_power;
  g_ip->area_wt = obj_func_area;
  g_ip->cycle_time_wt    = obj_func_cycle_time;
  g_ip->delay_dev = dev_func_delay;
  g_ip->dynamic_power_dev = dev_func_dynamic_power;
  g_ip->leakage_power_dev = dev_func_leakage_power;
  g_ip->area_dev = dev_func_area;
  g_ip->cycle_time_dev    = dev_func_cycle_time;
  g_ip->temp = temp;
  g_ip->ed = ed_ed2_none;

  g_ip->F_sz_nm         = tech_node;
  g_ip->F_sz_um         = tech_node / 1000;
  g_ip->default_device_files();
  g_ip->is_main_mem     = (main_mem != 0) ? true : false;
  g_ip->is_cache        = (cache ==1) ? true : false;
  g_ip->pure_ram        = (cache ==0) ? true : false;
  g_ip->pure_cam        = (cache ==2) ? true : false;
  g_ip->rpters_in_htree = (REPEATERS_IN_HTREE_SEGMENTS_in != 0) ? true : false;
  g_ip->ver_htree_wires_over_array = VERTICAL_HTREE_WIRES_OVER_THE_ARRAY_in;
  g_ip->broadcast_addr_din_over_ver_htrees = BROADCAST_ADDR_DATAIN_OVER_VERTICAL_HTREES_in;

  g_ip->num_rw_ports    = rw_ports;
  g_ip->num_rd_ports    = excl_read_ports;
  g_ip->num_wr_ports    = excl_write_ports;
  g_ip->num_se_rd_ports = single_ended_read_ports;
  g_ip->num_search_ports = search_ports;

  g_ip->print_detail = 1;
  g_ip->nuca = 0;

  if (force_wiretype == 0)
  {
	  g_ip->wt = Global;
      g_ip->force_wiretype = false;
  }
  else
  {   g_ip->force_wiretype = true;
	  if (wiretype==10) {
		  g_ip->wt = Global_10;
	        }
	  if (wiretype==20) {
		  g_ip->wt = Global_20;
	        }
	  if (wiretype==30) {
		  g_ip->wt = Global_30;
	        }
	  if (wiretype==5) {
	      g_ip->wt = Global_5;
	        }
	  if (wiretype==0) {
		  g_ip->wt = Low_swing;
	  }
  }
  //g_ip->wt = Global_5;
  if (force_config == 0)
    {
  	  g_ip->force_cache_config = false;
    }
    else
    {
    	g_ip->force_cache_config = true;
    	g_ip->ndbl=ndbl;
    	g_ip->ndwl=ndwl;
    	g_ip->nspd=nspd;
    	g_ip->ndcm=ndcm;
    	g_ip->ndsam1=ndsam1;
    	g_ip->ndsam2=ndsam2;
    }

  if (ecc==0){
	  g_ip->add_ecc_b_=false;
  }
  else
  {
	  g_ip->add_ecc_b_=true;
  }


  if(!g_ip->error_checking())
	  exit(0);

//  init_tech_params(g_ip->F_sz_um, false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //Divya added wire_technology
Wire winit; // Do not delete this line. It initializes wires.

  g_ip->display_ip();
  solve(&fin_res);
  output_UCA(&fin_res);
  output_data_csv(fin_res);
  delete (g_ip);

  return fin_res;
}
//divya end

bool InputParameter::error_checking()
{
  int  A;
  bool seq_access  = false;
  fast_access = true;
  fully_assoc = false;

  ///if ( (is_finfet && F_sz_nm != 7) || (!is_finfet && F_sz_nm == 7) ) // Alireza
  ///  return false;
  
  /// near-threshold only valid for finfet
  /// finfet just supports hp devices?
  /// finfet just supports 5nm (just HP), 7nm (just HP), and maybe 32nm
  /// near-threshold not yet
  
  switch (access_mode)
  {
    case 0:
      seq_access  = false;
      fast_access = false;
      break;
    case 1:
      seq_access  = true;
      fast_access = false;
      break;
    case 2:
      seq_access  = false;
      fast_access = true;
      break;
  }

  if(is_main_mem)
  {
    if(ic_proj_type == 0)
    {
      cerr << "DRAM model supports only conservative interconnect projection!\n\n";
      return false;
    }
  }

  uint32_t B = line_sz;

  if (B < 1)
  {
    cerr << "Block size must >= 1" << endl;
    return false;
  }
  else if (B*8 < out_w)
  {
    cerr << "Block size must be at least " << out_w/8 << endl;
    return false;
  }

  if (F_sz_um <= 0)
  {
    cerr << "Feature size must be > 0" << endl;
    return false;
  }
  else if (F_sz_um > 0.091)
  {
    cerr << "Feature size must be <= 90 nm" << endl;
    return false;
  }


  uint32_t RWP  = num_rw_ports;
  uint32_t ERP  = num_rd_ports;
  uint32_t EWP  = num_wr_ports;
  uint32_t NSER = num_se_rd_ports;
  uint32_t SCHP = num_search_ports;

  //  The number of ports specified at input is per bank
  if ((RWP+ERP+EWP) < 1)
  {
    cerr << "Must have at least one port" << endl;
    return false;
  }

  if (is_pow2(nbanks) == false)
  {
    cerr << "Number of subbanks should be greater than or equal to 1 and should be a power of 2" << endl;
    return false;
  }

  int C = cache_sz/nbanks;
  if (C < 64)
  {
    cerr << "Cache size must >=64" << endl;
    return false;
  }
  //added 10-11-2021 divya acdng to McPAT-CACTI
  //fully assoc and cam check
  if (is_cache && assoc==0)
  	fully_assoc =true;
  else
  	fully_assoc = false;

  if (pure_cam==true && assoc!=0)
  {
	  cerr << "Pure CAM must have associativity as 0" << endl;
	  return false;
  }

  if (assoc==0 && (pure_cam==false && is_cache ==false))
  {
	  cerr << "Only CAM or Fully associative cache can have associativity as 0" << endl;
	  return false;
  }

  if ((fully_assoc==true || pure_cam==true)
		  &&  (data_arr_ram_cell_tech_type!= tag_arr_ram_cell_tech_type
				 || data_arr_peri_global_tech_type != tag_arr_peri_global_tech_type  ))
  {
	  cerr << "CAM and fully associative cache must have same device type for both data and tag array" << endl;
	  return false;
  }

  if ((fully_assoc==true || pure_cam==true)
		  &&  (data_arr_ram_cell_tech_type== lp_dram || data_arr_ram_cell_tech_type== comm_dram))
  {
	  cerr << "DRAM based CAM and fully associative cache are not supported" << endl;
	  return false;
  }

  if ((fully_assoc==true || pure_cam==true)
		  &&  (is_main_mem==true))
  {
	  cerr << "CAM and fully associative cache cannot be as main memory" << endl;
	  return false;
  }

  if ((fully_assoc || pure_cam) && SCHP<1)
  {
	  cerr << "CAM and fully associative must have at least 1 search port" << endl;
	  return false;
  }

 if (RWP==0 && ERP==0 && SCHP>0 && ((fully_assoc || pure_cam)))
  {
	  ERP=SCHP;
  }


  if (assoc == 0)
  {
    A = C/B;
    //fully_assoc = true;
  }
  else
  {
    if (assoc == 1)
    {
      A = 1;
      //fully_assoc = false;
    }
    else
    {
      //fully_assoc = false;
      A = assoc;
      if (is_pow2(A) == false)
      {
        cerr << "Associativity must be a power of 2" << endl;
        return false;
      }
    }
  }

//  if (C/(B*A) <= 1 && !fully_assoc)
  if (C/(B*A) <= 1 && assoc!=0)
  {
    cerr << "Number of sets is too small: " << endl;
    cerr << " Need to either increase cache size, or decrease associativity or block size" << endl;
    cerr << " (or use fully associative cache)" << endl;
    return false;
  }

  block_sz = B;

  /*dt: testing sequential access mode*/
  if(seq_access)
  {
    tag_assoc  = A;
    data_assoc = 1;
    is_seq_acc = true;
  }
  else
  {
    tag_assoc  = A;
    data_assoc = A;
    is_seq_acc = false;
  }

  if (assoc==0)
  {
    data_assoc = 1;
  }
  num_rw_ports    = RWP;
  num_rd_ports    = ERP;
  num_wr_ports    = EWP;
  num_se_rd_ports = NSER;
  if (!(fully_assoc || pure_cam))
    num_search_ports = 0;
  nsets           = C/(B*A);

  if (temp < 300 || temp > 400 || temp%10 != 0)
  {
    cerr << temp << " Temperature must be between 300 and 400 Kelvin and multiple of 10." << endl;
    return false;
  }

  if (nsets < 1)
  {
    cerr << "Less than one set..." << endl;
    return false;
  }

  return true;
}



void output_data_csv(const uca_org_t & fin_res)
{
  fstream file("out.csv", ios::in);
  bool    print_index = file.fail();
  file.close();

  file.open("out.csv", ios::out|ios::app);
  if (file.fail() == true)
  {
    cerr << "File out.csv could not be opened successfully" << endl;
  }
  else
  {
    if (print_index == true)
    {
      file << "Tech node (nm), ";
      file << "Capacity (bytes), ";
      file << "Number of banks, ";
      file << "Associativity, ";
      file << "Output width (bits), ";
      file << "Access time (ns), ";
      file << "Random cycle time (ns), ";
      file << "Multisubbank interleave cycle time (ns), ";
      file << "Delay request network (ns), ";
      file << "Delay inside mat (ns), ";
      file << "Delay reply network (ns), ";
      file << "Tag array access time (ns), ";
      file << "Refresh period (microsec), ";
      file << "DRAM array availability (%), ";
      file << "Dynamic search energy (nJ), ";
      file << "Dynamic read energy (nJ), ";
      file << "Dynamic write energy (nJ), ";
      file << "Dynamic read power (mW), ";
      file << "Standby leakage per bank(mW), ";
      file << "Leakage per bank with leak power management (mW), ";
      file << "Refresh power as percentage of standby leakage, ";
      file << "Area (mm2), ";
      file << "Ndwl, ";
      file << "Ndbl, ";
      file << "Nspd, ";
      file << "Ndcm, ";
      file << "Ndsam_level_1, ";
      file << "Ndsam_level_2, ";
      file << "Ntwl, ";
      file << "Ntbl, ";
      file << "Ntspd, ";
      file << "Ntcm, ";
      file << "Ntsam_level_1, ";
      file << "Ntsam_level_2, ";
      file << "Area efficiency, ";
      file << "Resistance per unit micron (ohm-micron), ";
      file << "Capacitance per unit micron (fF per micron), ";
      file << "Unit-length wire delay (ps), ";
      file << "FO4 delay (ps), ";
      file << "delay route to bank (including crossb delay) (ps), ";
      file << "Crossbar delay (ps), ";
      file << "Dyn read energy per access from closed page (nJ), ";
      file << "Dyn read energy per access from open page (nJ), ";
      file << "Leak power of an subbank with page closed (mW), ";
      file << "Leak power of a subbank with page  open (mW), ";
      file << "Leak power of request and reply networks (mW), ";
      file << "Number of subbanks, ";
      file << "Page size in bits, ";
      file << "Activate power, ";
      file << "Read power, ";
      file << "Write power, ";
      file << "Precharge power, ";
      file << "tRCD, ";
      file << "CAS latency, ";
      file << "Precharge delay, ";
      file << "Perc dyn energy bitlines, ";
      file << "perc dyn energy wordlines, ";
      file << "perc dyn energy outside mat, ";
      file << "Area opt (perc), ";
      file << "Delay opt (perc), ";
      file << "Repeater opt (perc), ";
      file << "Aspect ratio" << endl;
    }
    file << g_ip->F_sz_nm << ", ";
    file << g_ip->cache_sz << ", ";
    file << g_ip->nbanks << ", ";
    file << g_ip->tag_assoc << ", ";
    file << g_ip->out_w << ", ";
    file << fin_res.access_time*1e+9 << ", ";
    file << fin_res.cycle_time*1e+9 << ", ";
    file << fin_res.data_array.multisubbank_interleave_cycle_time*1e+9 << ", ";
    file << fin_res.data_array.delay_request_network*1e+9 << ", ";
    file << fin_res.data_array.delay_inside_mat*1e+9 <<  ", ";
    file << fin_res.data_array.delay_reply_network*1e+9 << ", ";
    file << fin_res.tag_array.access_time*1e+9 << ", ";
    file << fin_res.data_array.dram_refresh_period*1e+6 << ", ";
    file << fin_res.data_array.dram_array_availability <<  ", ";
    file << fin_res.power.readOp.dynamic*1e+9 << ", ";
    file << fin_res.power.writeOp.dynamic*1e+9 << ", ";
    file << fin_res.power.readOp.dynamic*1000/fin_res.cycle_time << ", ";
    file << fin_res.power.readOp.leakage*1000 << ", ";
    file << fin_res.leak_power_with_sleep_transistors_in_mats*1000 << ", ";
    file << fin_res.data_array.refresh_power / fin_res.data_array.total_power.readOp.leakage << ", ";
    file << fin_res.area << ", ";
    file << fin_res.data_array.Ndwl << ", ";
    file << fin_res.data_array.Ndbl << ", ";
    file << fin_res.data_array.Nspd << ", ";
    file << fin_res.data_array.deg_bl_muxing << ", ";
    file << fin_res.data_array.Ndsam_lev_1 << ", ";
    file << fin_res.data_array.Ndsam_lev_2 << ", ";
    file << fin_res.tag_array.Ndwl << ", ";
    file << fin_res.tag_array.Ndbl << ", ";
    file << fin_res.tag_array.Nspd << ", ";
    file << fin_res.tag_array.deg_bl_muxing << ", ";
    file << fin_res.tag_array.Ndsam_lev_1 << ", ";
    file << fin_res.tag_array.Ndsam_lev_2 << ", ";
    file << fin_res.area_efficiency << ", ";
    file << g_tp.wire_inside_mat.R_per_um << ", ";
    file << g_tp.wire_inside_mat.C_per_um / 1e-15 << ", ";
    file << g_tp.unit_len_wire_del / 1e-12 << ", ";
    file << g_tp.FO4 / 1e-12 << ", ";
    file << fin_res.data_array.delay_route_to_bank / 1e-9 << ", ";
    file << fin_res.data_array.delay_crossbar / 1e-9 << ", ";
    file << fin_res.data_array.dyn_read_energy_from_closed_page / 1e-9 << ", ";
    file << fin_res.data_array.dyn_read_energy_from_open_page / 1e-9 << ", ";
    file << fin_res.data_array.leak_power_subbank_closed_page / 1e-3 << ", ";
    file << fin_res.data_array.leak_power_subbank_open_page / 1e-3 << ", ";
    file << fin_res.data_array.leak_power_request_and_reply_networks / 1e-3 << ", ";
    file << fin_res.data_array.number_subbanks << ", " ;
    file << fin_res.data_array.page_size_in_bits << ", " ;
    file << fin_res.data_array.activate_energy * 1e9 << ", " ;
    file << fin_res.data_array.read_energy * 1e9 << ", " ;
    file << fin_res.data_array.write_energy * 1e9 << ", " ;
    file << fin_res.data_array.precharge_energy * 1e9 << ", " ;
    file << fin_res.data_array.trcd * 1e9 << ", " ;
    file << fin_res.data_array.cas_latency * 1e9 << ", " ;
    file << fin_res.data_array.precharge_delay * 1e9 << ", " ;
    file << fin_res.data_array.all_banks_height / fin_res.data_array.all_banks_width << endl;
  }
  file.close();
}

//Divya begin
void output_UCA(uca_org_t *fr)
{
//	bool dvs = g_ip->is_dvs;
//	double dvs_volt_step = 0.1;
//	int dvs_levels = (g_ip->dvs_end - g_ip->dvs_start)/dvs_volt_step + 1;

	int dvs_levels = g_ip->dvs_voltage.size();
	int i;
	bool dvs  = !g_ip->dvs_voltage.empty();

  if (0) {
    cout << "\n\n Detailed Bank Stats:\n";
    cout << "    Bank Size (bytes): %d\n" <<
                                     (int) (g_ip->cache_sz);
  }
  else {
    if (g_ip->data_arr_ram_cell_tech_type == 3) {
      cout << "\n---------- P-CACTI, Uniform Cache Access " <<
        "Logic Process Based DRAM Model ----------\n";
    }
    else if (g_ip->data_arr_ram_cell_tech_type == 4) {
      cout << "\n---------- P-CACTI, Uniform" <<
        "Cache Access Commodity DRAM Model ----------\n";
    }
    else {
      cout << "\n---------- P-CACTI, Uniform Cache Access "
        "SRAM Model ----------\n";
    }
    cout << "\nCache Parameters:\n";
    cout << "    Total cache size (bytes): " <<
      (int) (g_ip->cache_sz) << endl;
  }

  cout << "    Number of banks: " << (int) g_ip->nbanks << endl;
    if (g_ip->fully_assoc)
      cout << "    Associativity: fully associative\n";
    else {
      if (g_ip->tag_assoc == 1)
        cout << "    Associativity: direct mapped\n";
      else
        cout << "    Associativity: " <<
          g_ip->tag_assoc << endl;
    }


    cout << "    Block size (bytes): " << g_ip->line_sz << endl;
    cout << "    Read/write Ports: " <<
      g_ip->num_rw_ports << endl;
    cout << "    Read ports: " <<
      g_ip->num_rd_ports << endl;
    cout << "    Write ports: " <<
      g_ip->num_wr_ports << endl;;
    if (g_ip->fully_assoc|| g_ip->pure_cam)
  	  cout << "    search ports: " <<
  	      g_ip->num_search_ports << endl;
    cout << "    Technology size (nm): " <<
      g_ip->F_sz_nm << endl << endl;

  if (dvs)
  {
	 cout << "    Access time (ns): ";
	 for (i = 0; i<dvs_levels; i++)
		  cout<<fr->uca_q[i]->access_time*1e9 <<";";
	 cout << endl;
  }
  else
	  cout << "    Access time (ns): " << fr->access_time*1e9 << endl;


  if (dvs)
  {
	  cout << "    Cycle time (ns):  " ;
	 for (i = 0; i<dvs_levels; i++)
		  cout<<fr->uca_q[i]->cycle_time*1e9 <<"; ";
	 cout<< endl;
  }
  else
  cout << "    Cycle time (ns):  " << fr->cycle_time*1e9 << endl;


  if (g_ip->data_arr_ram_cell_tech_type >= 4) {
    cout << "    Precharge Delay (ns): " << fr->data_array2.precharge_delay*1e9 << endl;
    cout << "    Activate Energy (nJ): " << fr->data_array2.activate_energy*1e9 << endl;
    cout << "    Read Energy (nJ): " << fr->data_array2.read_energy*1e9 << endl;
    cout << "    Write Energy (nJ): " << fr->data_array2.write_energy*1e9 << endl;
    cout << "    Precharge Energy (nJ): " << fr->data_array2.precharge_energy*1e9 << endl;
    cout << "    Leakage Power Closed Page (mW): " << fr->data_array2.leak_power_subbank_closed_page*1e3 << endl;
    cout << "    Leakage Power Open Page (mW): " << fr->data_array2.leak_power_subbank_open_page*1e3 << endl;
    cout << "    Leakage Power I/O (mW): " << fr->data_array2.leak_power_request_and_reply_networks*1e3 << endl;
    cout << "    Refresh power (mW): " <<
      fr->data_array2.refresh_power*1e3 << endl;
  }
  else {
	  if ((g_ip->fully_assoc|| g_ip->pure_cam))
	  {
		  if (dvs)
		  {
			  cout << "    Total dynamic associative search energy per access (nJ): ";
			  for (i = 0; i<dvs_levels; i++)
				  cout<<fr->uca_q[i]->power.searchOp.dynamic*1e9 <<"; ";
			  cout<< endl;
		  }
		  else
			  cout << "    Total dynamic associative search energy per access (nJ): " <<
					  fr->power.searchOp.dynamic*1e9;

			  //		  cout << "    Total dynamic read energy per access (nJ): " <<
		  //		  fr->power.readOp.dynamic*1e9 << endl;
		  //		  cout << "    Total dynamic write energy per access (nJ): " <<
		  //		  fr->power.writeOp.dynamic*1e9 << endl;
	  }
	  if (dvs)
	  {
		  cout << "    Total dynamic read energy per access (nJ): ";
		  for (i = 0; i<dvs_levels; i++)
			  cout<<fr->uca_q[i]->power.readOp.dynamic*1e9 <<"; ";
		  cout<< endl;
		  cout << "    Total dynamic write energy per access (nJ): ";
		  for (i = 0; i<dvs_levels; i++)
		 			  cout<<fr->uca_q[i]->power.writeOp.dynamic*1e9 <<"; ";
		  cout<< endl;
		  cout << "    Total leakage power of a bank (mW): ";
		  for (i = 0; i<dvs_levels; i++)
			  cout<< fr->uca_q[i]->power.readOp.leakage*1e3 <<"; ";
		  cout<< endl;
 	  }
	  else {
		cout << "    Total dynamic read energy per access (nJ): " <<
		  fr->power.readOp.dynamic*1e9 << endl;
		cout << "    Total dynamic write energy per access (nJ): " << // Alireza
		  fr->power.writeOp.dynamic*1e9 << endl;                      // Alireza
		cout << "    Total leakage power of a bank"
		  " (mW): " << fr->power.readOp.leakage*1e3 << endl;
	  }
  }

  if (g_ip->data_arr_ram_cell_tech_type ==3 || g_ip->data_arr_ram_cell_tech_type ==4)
  {
  }
  if (dvs) {
	  cout <<  "    Cache height x width (mm): ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->cache_ht*1e-3 << " x " << fr->cache_len*1e-3 << "; ";
	  cout<< endl;
	  cout <<  "    Cache area (mm2): ";
	  for (i = 0; i<dvs_levels; i++)
		  cout <<	fr->uca_q[i]->area*1e-3*1e-3 << "; ";
	  cout<< endl << endl;
  } else {
	 cout <<  "    Cache height x width (mm): " <<
		fr->cache_ht*1e-3 << " x " << fr->cache_len*1e-3 << endl;
	  cout <<  "    Cache area (mm2): " <<
		fr->area*1e-3*1e-3 << endl << endl;
  	  }
  if (dvs) {
	  cout << "    Best Ndwl : ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->data_array2.Ndwl << "; ";
	  cout<< endl;

	  cout << "    Best Ndbl : ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->data_array2.Ndbl << "; ";
	  cout<< endl;

	  cout << "    Best Nspd : ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->data_array2.Nspd << "; ";
	  cout<< endl;

	  cout << "    Best Ndcm : ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->data_array2.deg_bl_muxing << "; ";
	  cout<< endl;

	  cout << "    Best Ndsam L1 : ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->data_array2.Ndsam_lev_1 << "; ";
	  cout<< endl;


	  cout << "    Best Ndsam L2 : ";
	  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->data_array2.Ndsam_lev_2 << "; ";
	  cout<< endl << endl;

  } else {
  cout << "    Best Ndwl : " << fr->data_array2.Ndwl << endl;
  cout << "    Best Ndbl : " << fr->data_array2.Ndbl << endl;
  cout << "    Best Nspd : " << fr->data_array2.Nspd << endl;
  cout << "    Best Ndcm : " << fr->data_array2.deg_bl_muxing << endl;
  cout << "    Best Ndsam L1 : " << fr->data_array2.Ndsam_lev_1 << endl;
  cout << "    Best Ndsam L2 : " << fr->data_array2.Ndsam_lev_2 << endl << endl;

  }

  if ((!(g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)) && !g_ip->is_main_mem)
  {
	  if(dvs) {
		  cout << "    Best Ntwl : ";
		  for (i = 0; i<dvs_levels; i++)
			  cout << fr->uca_q[i]->tag_array2.Ndwl << ";";
		  cout<< endl;

		  cout << "    Best Ntbl : ";
		  for (i = 0; i<dvs_levels; i++)
			cout << fr->uca_q[i]->tag_array2.Ndbl << ";";
 		  cout<< endl;

 		  cout << "    Best Ntspd : ";
		  for (i = 0; i<dvs_levels; i++)
			cout << fr->uca_q[i]->tag_array2.Nspd << ";";
		  cout<< endl;

		  cout << "    Best Ntcm : ";
		  for (i = 0; i<dvs_levels; i++)
			cout << fr->uca_q[i]->tag_array2.deg_bl_muxing << ";";
  		  cout<< endl;

		  cout << "    Best Ntsam L1 : ";
		  for (i = 0; i<dvs_levels; i++)
			cout << fr->uca_q[i]->tag_array2.Ndsam_lev_1 << ";";
		  cout<< endl;

		  cout << "    Best Ntsam L2 : ";
		  for (i = 0; i<dvs_levels; i++)
			cout << fr->uca_q[i]->tag_array2.Ndsam_lev_2 << ";";
		  cout<< endl;

	  } else {
		cout << "    Best Ntwl : " << fr->tag_array2.Ndwl << endl;
		cout << "    Best Ntbl : " << fr->tag_array2.Ndbl << endl;
		cout << "    Best Ntspd : " << fr->tag_array2.Nspd << endl;
		cout << "    Best Ntcm : " << fr->tag_array2.deg_bl_muxing << endl;
		cout << "    Best Ntsam L1 : " << fr->tag_array2.Ndsam_lev_1 << endl;
		cout << "    Best Ntsam L2 : " << fr->tag_array2.Ndsam_lev_2 << endl;
	  }
  }

//  cout << "dataarray wt " << fr->data_array2.wt << endl;
  switch (fr->data_array2.wt) {
    case (0):
      cout <<  "    Data array, H-tree wire type: Delay optimized global wires\n";
      break;
    case (1):
      cout <<  "    Data array, H-tree wire type: Global wires with 5\% delay penalty\n";
      break;
    case (2):
      cout <<  "    Data array, H-tree wire type: Global wires with 10\% delay penalty\n";
      break;
    case (3):
      cout <<  "    Data array, H-tree wire type: Global wires with 20\% delay penalty\n";
      break;
    case (4):
      cout <<  "    Data array, H-tree wire type: Global wires with 30\% delay penalty\n";
      break;
    case (5):
      cout <<  "    Data array, wire type: Low swing wires\n";
      break;
    default:
      cout << "ERROR - Unknown wire type " << (int) fr->data_array2.wt <<endl;
      exit(0);
  }

  if (!(g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)) {
    switch (fr->tag_array2.wt) {
      case (0):
        cout <<  "    Tag array, H-tree wire type: Delay optimized global wires\n";
        break;
      case (1):
        cout <<  "    Tag array, H-tree wire type: Global wires with 5\% delay penalty\n";
        break;
      case (2):
        cout <<  "    Tag array, H-tree wire type: Global wires with 10\% delay penalty\n";
        break;
      case (3):
        cout <<  "    Tag array, H-tree wire type: Global wires with 20\% delay penalty\n";
        break;
      case (4):
        cout <<  "    Tag array, H-tree wire type: Global wires with 30\% delay penalty\n";
        break;
      case (5):
        cout <<  "    Tag array, wire type: Low swing wires\n";
        break;
      default:
        cout << "ERROR - Unknown wire type " << (int) fr->tag_array2.wt <<endl;
        exit(-1);
    }
  }

  if (g_ip->print_detail)
  {
//    if(g_ip->fully_assoc) return;

    /* Delay stats */
    /* data array stats */
    cout << endl << "Time Components:" << endl << endl;

    if (dvs)
     {
     	cout<< "Data side (with Output driver) (ns): ";
     	for (i = 0; i<dvs_levels; i++)
     		cout<<fr->uca_q[i]->data_array2.access_time/1e-9 <<"; ";
     	cout << endl;
     } else {
    cout << "  Data side (with Output driver) (ns): " <<
      fr->data_array2.access_time/1e-9 << endl;
     }

    if (dvs)
   {
	 cout <<  "\tH-tree delay outside banks (ns) : " ;
	for (i = 0; i<dvs_levels; i++)
		cout<<fr->uca_q[i]->data_array2.delay_route_to_bank * 1e9 <<"; ";
	cout << endl;
   } else {
	   cout <<  "\tH-tree delay outside banks (ns) : " <<
			 fr->data_array2.delay_route_to_bank * 1e9 << endl;
   }

	if (dvs)
	{
		cout<<"\tH-tree input delay (inside a bank) (ns) :  ";
		for (i = 0; i<dvs_levels; i++)
			cout<<fr->uca_q[i]->data_array2.delay_input_htree * 1e9 <<"; ";
	}
	else {
		 cout <<  "\tH-tree input delay (inside a bank) (ns) : " <<
					  fr->data_array2.delay_input_htree * 1e9 ;
	}
	cout<< endl;

	if (!(g_ip->pure_cam || g_ip->fully_assoc))
	{
		cout <<  "\tDecoder + wordline delay (ns): ";
		if (dvs)
		{
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.delay_row_predecode_driver_and_block * 1e9 +
					fr->uca_q[i]->data_array2.delay_row_decoder * 1e9 <<"; ";
			cout << endl;
		} else {
		  cout << fr->data_array2.delay_row_predecode_driver_and_block * 1e9 +
		  fr->data_array2.delay_row_decoder * 1e9 << endl;
		}
	}
	else
	{
	   cout <<  "\tCAM search delay (ns): " ;
	   if (dvs)
	   {
		for (i = 0; i<dvs_levels; i++)
			cout<<fr->uca_q[i]->data_array2.delay_matchlines * 1e9  <<"; ";
		cout<< endl;
	   }
	   else
			  cout << fr->data_array2.delay_matchlines * 1e9 << endl;
	}

	cout <<  "\tBitline delay (ns): ";
    if(dvs) {
    	for (i = 0; i<dvs_levels; i++)
    	    cout<<fr->uca_q[i]->data_array2.delay_bitlines/1e-9  <<"; ";
    	cout << endl;
    }
    else {
     cout << fr->data_array2.delay_bitlines/1e-9 << endl;
    }

    cout <<  "\tSense Amplifier delay (ns): ";
    if(dvs) {
    	for (i = 0; i<dvs_levels; i++)
    		cout<<fr->uca_q[i]->data_array2.delay_sense_amp*1e9  <<"; ";
    	cout << endl;
    } else {
     cout << fr->data_array2.delay_sense_amp * 1e9 << endl;
    }

    cout <<  "\tH-tree output delay (inside a bank) (ns): ";
    if(dvs) {
    	for (i = 0; i<dvs_levels; i++)
    		cout<<fr->uca_q[i]->data_array2.delay_subarray_output_driver * 1e9 +
    	      		fr->uca_q[i]->data_array2.delay_dout_htree * 1e9  <<"; ";
    	cout << endl;
    } else {
     cout << fr->data_array2.delay_subarray_output_driver * 1e9 +
      fr->data_array2.delay_dout_htree * 1e9 << endl;
    }

    if ((!(g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)) && !g_ip->is_main_mem)
    {
      /* tag array stats */
      cout << endl << "  Tag side (with Output driver) (ns): " ;

      if(dvs) {
    	  for (i = 0; i<dvs_levels; i++)
    	    cout<<fr->uca_q[i]->tag_array2.access_time/1e-9  <<"; ";
    	  cout << endl;
      }
      else {
    	  cout << fr->tag_array2.access_time/1e-9 << endl;
      }

      if(dvs) {
    	  cout <<  "\tH-tree input delay (ns): " ;
          for (i = 0; i<dvs_levels; i++)
        	  cout<<fr->uca_q[i]->tag_array2.delay_route_to_bank * 1e9  <<"; ";
          cout << endl;

      } else {
    	  cout <<  "\tH-tree delay outside banks (ns) : " <<
    	          fr->tag_array2.delay_route_to_bank * 1e9;
      }

      cout <<  "\tH-tree input delay (inside a bank) (ns) : ";
	  if (dvs)
	  {
		for (i = 0; i<dvs_levels; i++)
			cout<<fr->uca_q[i]->tag_array2.delay_input_htree * 1e9  <<"; ";
	  }
	  else {
		cout <<  fr->tag_array2.delay_input_htree * 1e9;
	  }
	  cout << endl;

	  if(dvs)
	  {
		  cout <<  "\tDecoder + wordline delay (ns): ";
		  for (i = 0; i<dvs_levels; i++)
		  cout << fr->uca_q[i]->tag_array2.delay_row_predecode_driver_and_block * 1e9 +
		          fr->uca_q[i]->tag_array2.delay_row_decoder * 1e9 << ";";
		  cout << endl;
	  } else {
		  cout <<  "\tDecoder + wordline delay (ns): " <<
			fr->tag_array2.delay_row_predecode_driver_and_block * 1e9 +
			fr->tag_array2.delay_row_decoder * 1e9 << endl;
	  }

      cout <<  "\tBitline delay (ns): ";
      if(dvs) {
		for (i = 0; i<dvs_levels; i++)
			cout<<fr->uca_q[i]->tag_array2.delay_bitlines * 1e9  <<"; ";
		cout << endl;
      } else {
       cout << fr->tag_array2.delay_bitlines/1e-9 << endl;
      }

      cout <<  "\tSense Amplifier delay (ns): ";
      if(dvs) {
       	for (i = 0; i<dvs_levels; i++)
        	cout<<fr->uca_q[i]->tag_array2.delay_sense_amp * 1e9  <<"; ";
    	 cout  << endl;
      } else
         cout << fr->tag_array2.delay_sense_amp * 1e9 << endl;

      cout <<  "\tComparator delay (ns): ";
      if(dvs) {
		for (i = 0; i<dvs_levels; i++)
			cout<<fr->uca_q[i]->tag_array2.delay_comparator * 1e9  <<"; ";
		cout << endl;
      } else {
       cout << fr->tag_array2.delay_comparator * 1e9 << endl;
      }

      cout <<  "\tH-tree output delay (inside a bank) (ns): ";
      if(dvs) {
        	for (i = 0; i<dvs_levels; i++)
        		cout<<fr->uca_q[i]->tag_array2.delay_subarray_output_driver * 1e9 +
					fr->uca_q[i]->tag_array2.delay_dout_htree * 1e9  <<"; ";
    	 cout << endl;
      } else {
        cout << fr->tag_array2.delay_subarray_output_driver * 1e9 +
        fr->tag_array2.delay_dout_htree * 1e9 << endl;
      }
    }

    /* Energy/Power stats */
    cout << endl << endl << "Power Components:" << endl << endl;
    if (!(g_ip->pure_cam || g_ip->fully_assoc))
    {
		if(dvs) {
			 cout << "  Data array: \n Total dynamic read energy/access  (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power.readOp.dynamic * 1e9 << "; ";
			cout << endl;

			cout << "Total dynamic write energy/access  (nJ): " ;
					for (i = 0; i<dvs_levels; i++)
						cout <<  fr->uca_q[i]->data_array2.power.writeOp.dynamic * 1e9 << "; ";
			cout << endl;
		} else {
			cout << "  Data array: \n Total dynamic read energy/access  (nJ): " <<
			  fr->data_array2.power.readOp.dynamic * 1e9 << endl;
			   cout << "Total dynamic write energy/access (nJ): " <<
				 fr->data_array2.power.writeOp.dynamic * 1e9 << endl;
		}
		if(dvs) {
			cout << "\tTotal leakage read/write power of a bank (mW): ";
			for (i = 0; i<dvs_levels; i++)
			cout <<fr->uca_q[i]->data_array2.power.readOp.leakage * 1e3 << "; ";
				 cout << endl;
		   } else
			   cout << "\tTotal leakage read/write power of a bank (mW): " <<
			fr->data_array2.power.readOp.leakage * 1e3 << endl;

		if(dvs) {
			cout << "\tTotal energy in H-tree outside banks (that includes both "
				  "address and data transfer) (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout << (fr->uca_q[i]->data_array2.power_routing_to_bank.readOp.dynamic)*1e9 << "; ";
			cout << endl;
		   } else
			cout << "\tTotal energy in H-tree outside banks (that includes both "
			  "address and data transfer) (nJ): " <<
				(/*fr->data_array2.power_addr_input_htree.readOp.dynamic +
				 fr->data_array2.power_data_output_htree.readOp.dynamic +*/
				 fr->data_array2.power_routing_to_bank.readOp.dynamic) * 1e9 << endl;

		if(dvs) {
			cout << "\tInput H-tree inside bank Energy (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout <<  (fr->uca_q[i]->data_array2.power_addr_input_htree.readOp.dynamic) * 1e9 << "; ";
			cout << endl;
		   } else
			cout << "\tInput H-tree inside bank Energy (nJ): " <<
			(fr->data_array2.power_addr_input_htree.readOp.dynamic) * 1e9 << endl;

		if(dvs) {
			 cout << "\tOutput Htree Energy inside bank Energy (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power_data_output_htree.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
			cout << "\tOutput Htree Energy inside bank Energy (nJ): " <<
			  fr->data_array2.power_data_output_htree.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			 cout <<  "\tDecoder (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power_row_predecoder_drivers.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_row_predecoder_blocks.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
			cout <<  "\tDecoder (nJ): " <<
			  fr->data_array2.power_row_predecoder_drivers.readOp.dynamic * 1e9 +
			  fr->data_array2.power_row_predecoder_blocks.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			cout <<  "\tWordline (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power_row_decoders.readOp.dynamic * 1e9 <<  "; ";
			cout << endl;
		   } else
			cout <<  "\tWordline (nJ): " <<
			  fr->data_array2.power_row_decoders.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			cout <<  "\tBitline mux & associated drivers (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power_bit_mux_predecoder_drivers.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_bit_mux_predecoder_blocks.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_bit_mux_decoders.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
			cout <<  "\tBitline mux & associated drivers (nJ): " <<
			  fr->data_array2.power_bit_mux_predecoder_drivers.readOp.dynamic * 1e9 +
			  fr->data_array2.power_bit_mux_predecoder_blocks.readOp.dynamic * 1e9 +
			  fr->data_array2.power_bit_mux_decoders.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			cout <<  "\tSense amp mux & associated drivers (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_senseamp_mux_lev_1_decoders.readOp.dynamic * 1e9  +
				  fr->uca_q[i]->data_array2.power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic * 1e9 +
				  fr->uca_q[i]->data_array2.power_senseamp_mux_lev_2_decoders.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
			cout <<  "\tSense amp mux & associated drivers (nJ): " <<
			  fr->data_array2.power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic * 1e9 +
			  fr->data_array2.power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic * 1e9 +
			  fr->data_array2.power_senseamp_mux_lev_1_decoders.readOp.dynamic * 1e9  +
			  fr->data_array2.power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic * 1e9 +
			  fr->data_array2.power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic * 1e9 +
			  fr->data_array2.power_senseamp_mux_lev_2_decoders.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			cout <<  "\tBitlines (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout << fr->uca_q[i]->data_array2.power_bitlines.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
			cout <<  "\tBitlines (nJ): " <<
			  fr->data_array2.power_bitlines.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			cout <<  "\tSense amplifier energy (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout <<   fr->uca_q[i]->data_array2.power_sense_amps.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
			cout <<  "\tSense amplifier energy (nJ): " <<
			  fr->data_array2.power_sense_amps.readOp.dynamic * 1e9 << endl;

		if(dvs) {
			 cout <<  "\tSub-array output driver (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout <<  fr->uca_q[i]->data_array2.power_output_drivers_at_subarray.readOp.dynamic * 1e9 << "; ";
			cout << endl;
		   } else
				cout <<  "\tSub-array output driver (nJ): " <<
				  fr->data_array2.power_output_drivers_at_subarray.readOp.dynamic * 1e9 << endl;
	}

    if (g_ip->pure_cam||g_ip->fully_assoc)
    {
    	if (g_ip->pure_cam) cout << "  CAM array:"<<endl;
    	if (g_ip->fully_assoc)  cout << "  Fully associative array:"<<endl;

		if (dvs)
		{
			cout << "  Total dynamic associative search energy/access  (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power.searchOp.dynamic * 1e9  <<"; ";
			cout<< endl;
		}
		else
	    	cout << "  Total dynamic associative search energy/access  (nJ): " <<
	    	    			fr->data_array2.power.searchOp.dynamic * 1e9 ;

		if (dvs)
		 {
			cout << "\tTotal energy in H-tree outside banks(that includes both "
					"match key and data transfer) (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_routing_to_bank.searchOp.dynamic * 1e9 <<"; ";
			cout<< endl;
		 }
		else
			cout << "\tTotal energy in H-tree outside banks(that includes both "
					"match key and data transfer) (nJ): " <<
					(fr->data_array2.power_routing_to_bank.searchOp.dynamic) * 1e9;

		 if (dvs)
		 {
			 cout << "\tMatch Key input Htree inside bank Energy (nJ): " ;
			 for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_htree_in_search.searchOp.dynamic * 1e9 <<"; ";
			cout<< endl;
		 }
		 else
			 cout << "\tMatch Key input Htree inside bank Energy (nJ): " <<
			     	    			(fr->data_array2.power_htree_in_search.searchOp.dynamic ) * 1e9 ;

		 if (dvs)
		 {
			cout << "\tResult output Htrees inside bank Energy (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_htree_out_search.searchOp.dynamic * 1e9 <<"; ";
			 cout<< endl;
		 }
		 else
				cout << "\tResult output Htrees inside bank Energy (nJ): " <<
						(fr->data_array2.power_htree_out_search.searchOp.dynamic) * 1e9 ;

		cout <<  "\tSearchlines (nJ): " <<
				fr->data_array2.power_searchline.searchOp.dynamic * 1e9 +
				fr->data_array2.power_searchline_precharge.searchOp.dynamic * 1e9 ;
		 if (dvs)
		 {
				cout <<  "\tSearchlines (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_searchline.searchOp.dynamic * 1e9 +
					  fr->uca_q[i]->data_array2.power_searchline_precharge.searchOp.dynamic * 1e9 <<"; ";
				 cout<< endl;
		 }
		 else
				cout <<  "\tSearchlines (nJ): " <<
						fr->data_array2.power_searchline.searchOp.dynamic * 1e9 +
						fr->data_array2.power_searchline_precharge.searchOp.dynamic * 1e9 ;

		 if (dvs)
		 {
				cout <<  "\tMatchlines  (nJ): ";
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_matchlines.searchOp.dynamic * 1e9 +
					  fr->uca_q[i]->data_array2.power_matchline_precharge.searchOp.dynamic * 1e9 <<"; ";
			cout<< endl;
		}
		 else
				cout <<  "\tMatchlines  (nJ): " <<
						fr->data_array2.power_matchlines.searchOp.dynamic * 1e9 +
						fr->data_array2.power_matchline_precharge.searchOp.dynamic * 1e9;

		if (g_ip->fully_assoc)
		{
			 if (dvs)
			 {
					cout <<  "\tData portion wordline (nJ): " ;
				for (i = 0; i<dvs_levels; i++)
					cout<<fr->uca_q[i]->data_array2.power_matchline_to_wordline_drv.searchOp.dynamic * 1e9 <<"; ";
				 cout<< endl;
			 }
			 else
					cout <<  "\tData portion wordline (nJ): " <<
							fr->data_array2.power_matchline_to_wordline_drv.searchOp.dynamic * 1e9 ;

			 if (dvs)
			 {
				cout <<  "\tData Bitlines (nJ): " ;
				for (i = 0; i<dvs_levels; i++)
					cout<<(fr->uca_q[i]->data_array2.power_bitlines.searchOp.dynamic * 1e9 +
						   fr->uca_q[i]->data_array2.power_prechg_eq_drivers.searchOp.dynamic * 1e9) <<"; ";
				cout<< endl;
			}
			else
					cout <<  "\tData Bitlines (nJ): " <<
							fr->data_array2.power_bitlines.searchOp.dynamic * 1e9 +
							fr->data_array2.power_prechg_eq_drivers.searchOp.dynamic * 1e9;

			 if (dvs)
			 {
				cout <<  "\tSense amplifier energy (nJ): " ;
				for (i = 0; i<dvs_levels; i++)
					cout<<fr->uca_q[i]->data_array2.power_sense_amps.searchOp.dynamic * 1e9 <<"; ";
				 cout<< endl;
			 }
			 else
				 cout <<  "\tSense amplifier energy (nJ): " <<
						fr->data_array2.power_sense_amps.searchOp.dynamic * 1e9 ;
		}

		 if (dvs)
		 {
				cout <<  "\tSub-array output driver (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_output_drivers_at_subarray.searchOp.dynamic * 1e9 <<"; ";
			cout<< endl;
		}
		 else
				cout <<  "\tSub-array output driver (nJ): " <<
						fr->data_array2.power_output_drivers_at_subarray.searchOp.dynamic * 1e9 ;

		 if (dvs)
		 {
				cout <<endl<< "  Total dynamic read energy/access  (nJ): " ;
			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power.readOp.dynamic * 1e9 <<"; ";
			cout<< endl;
		}
		 else
				cout <<endl<< "  Total dynamic read energy/access  (nJ): " <<
						fr->data_array2.power.readOp.dynamic * 1e9;


		 if (dvs)
		 {
				cout << "\tTotal energy in H-tree outside banks(that includes both "
						"address and data transfer) (nJ): " ;

			for (i = 0; i<dvs_levels; i++)
				cout<<fr->uca_q[i]->data_array2.power_routing_to_bank.readOp.dynamic * 1e9 <<"; ";
		 		 cout<< endl;
		 }
		 else
				cout << "\tTotal energy in H-tree outside banks(that includes both "
						"address and data transfer) (nJ): " <<
						(fr->data_array2.power_routing_to_bank.readOp.dynamic) * 1e9;

			if (dvs)
			{
				cout << "\tInput Htree inside bank Energy (nJ): ";

				for (i = 0; i<dvs_levels; i++)
					cout<<fr->uca_q[i]->data_array2.power_addr_input_htree.readOp.dynamic * 1e9 <<"; ";
					 cout<< endl;
			} else
				cout << "\tInput Htree inside bank Energy (nJ): " <<
							(fr->data_array2.power_addr_input_htree.readOp.dynamic ) * 1e9 ;

			cout << "\tOutput Htree inside bank Energy (nJ): " <<
					fr->data_array2.power_data_output_htree.readOp.dynamic * 1e9 ;
			if (dvs)
			{
				cout << "\tOutput Htree inside bank Energy (nJ): " ;

				for (i = 0; i<dvs_levels; i++)
					cout<<fr->uca_q[i]->data_array2.power_data_output_htree.readOp.dynamic * 1e9 <<"; ";
					 cout<< endl;
			} else
				cout << "\tOutput Htree inside bank Energy (nJ): " <<
						fr->data_array2.power_data_output_htree.readOp.dynamic * 1e9 ;

			if (dvs)
			{
				cout <<  "\tDecoder (nJ): " ;

				for (i = 0; i<dvs_levels; i++)
					cout<<(fr->uca_q[i]->data_array2.power_row_predecoder_drivers.readOp.dynamic * 1e9 +
						   fr->uca_q[i]->data_array2.power_row_predecoder_blocks.readOp.dynamic * 1e9) <<"; ";
					 cout<< endl;
			} else
				cout <<  "\tDecoder (nJ): " <<
						fr->data_array2.power_row_predecoder_drivers.readOp.dynamic * 1e9 +
						fr->data_array2.power_row_predecoder_blocks.readOp.dynamic * 1e9;

			if (dvs)
			{
				cout <<  "\tWordline (nJ): " ;

				for (i = 0; i<dvs_levels; i++)
					cout<<fr->uca_q[i]->data_array2.power_row_decoders.readOp.dynamic * 1e9 <<"; ";
					 cout<< endl;
			} else
				cout <<  "\tWordline (nJ): " <<
						fr->data_array2.power_row_decoders.readOp.dynamic * 1e9 ;

	        if (dvs)
	        {
				cout <<  "\tBitline mux & associated drivers (nJ): " ;

	        	for (i = 0; i<dvs_levels; i++)
	        		cout<<(fr->uca_q[i]->data_array2.power_bit_mux_predecoder_drivers.readOp.dynamic * 1e9 +
	            			fr->uca_q[i]->data_array2.power_bit_mux_predecoder_blocks.readOp.dynamic * 1e9 +
	            			fr->uca_q[i]->data_array2.power_bit_mux_decoders.readOp.dynamic * 1e9)
	            			<<"; ";
		        cout<< endl;
	        }
	        else
				cout <<  "\tBitline mux & associated drivers (nJ): " <<
	    			fr->data_array2.power_bit_mux_predecoder_drivers.readOp.dynamic * 1e9 +
	    			fr->data_array2.power_bit_mux_predecoder_blocks.readOp.dynamic * 1e9 +
	    			fr->data_array2.power_bit_mux_decoders.readOp.dynamic * 1e9;

	        if (dvs)
	        {
		    	cout <<  "\tSense amp mux & associated drivers (nJ): " ;

	        	for (i = 0; i<dvs_levels; i++)
	        		cout<<( fr->uca_q[i]->data_array2.power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic * 1e9 +
	            			fr->uca_q[i]->data_array2.power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic * 1e9 +
	            			fr->uca_q[i]->data_array2.power_senseamp_mux_lev_1_decoders.readOp.dynamic * 1e9  +
	            			fr->uca_q[i]->data_array2.power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic * 1e9 +
	            			fr->uca_q[i]->data_array2.power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic * 1e9 +
	            			fr->uca_q[i]->data_array2.power_senseamp_mux_lev_2_decoders.readOp.dynamic * 1e9)
	            			<<"; ";
	        	cout<< endl;
	        }
	        else
		    	cout <<  "\tSense amp mux & associated drivers (nJ): " <<
		    			fr->data_array2.power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic * 1e9 +
		    			fr->data_array2.power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic * 1e9 +
		    			fr->data_array2.power_senseamp_mux_lev_1_decoders.readOp.dynamic * 1e9  +
		    			fr->data_array2.power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic * 1e9 +
		    			fr->data_array2.power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic * 1e9 +
		    			fr->data_array2.power_senseamp_mux_lev_2_decoders.readOp.dynamic * 1e9;

	        if (dvs)
	        {
		        cout <<  "\tBitlines (nJ): " ;

	        	for (i = 0; i<dvs_levels; i++)
	        		cout<<(fr->uca_q[i]->data_array2.power_bitlines.readOp.dynamic * 1e9 +
	    			       fr->uca_q[i]->data_array2.power_prechg_eq_drivers.readOp.dynamic* 1e9) <<"; ";
		        cout<< endl;
	        }
	        else
		        cout <<  "\tBitlines (nJ): " <<
		    			fr->data_array2.power_bitlines.readOp.dynamic * 1e9 +
		    			fr->data_array2.power_prechg_eq_drivers.readOp.dynamic * 1e9;

	        if (dvs)
	        {
		    	cout <<  "\tSense amplifier energy (nJ): " ;

	        	for (i = 0; i<dvs_levels; i++)
	        		cout<<fr->uca_q[i]->data_array2.power_sense_amps.readOp.dynamic * 1e9 <<"; ";
		        cout<< endl;
	        }
	        else
		    	cout <<  "\tSense amplifier energy (nJ): " <<
		    			fr->data_array2.power_sense_amps.readOp.dynamic * 1e9 ;

	        if (dvs)
	        {
		    	cout <<  "\tSub-array output driver (nJ): ";

	        	for (i = 0; i<dvs_levels; i++)
	        		cout<<fr->uca_q[i]->data_array2.power_output_drivers_at_subarray.readOp.dynamic * 1e9 <<"; ";
		        cout<< endl;
	        }
	        else
		    	cout <<  "\tSub-array output driver (nJ): " <<
		    			fr->data_array2.power_output_drivers_at_subarray.readOp.dynamic * 1e9 ;


	        if (dvs)
	        {
		    	cout << endl <<"  Total leakage power of a bank, including its network outside (mW): " ;

	        	for (i = 0; i<dvs_levels; i++)
	        		cout<< (fr->uca_q[i]->data_array2.power.readOp.leakage) * 1e3 <<"; ";
	        	cout<< endl;
	        }
	        else
		    	cout << endl <<"  Total leakage power of a bank, including its network outside (mW): " <<
		    			 (fr->data_array2.power.readOp.leakage)*1e3; //CAM/FA does not support PG yet

    }

//    if (g_ip->is_cache && !g_ip->is_main_mem)
    if ((!(g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)) && !g_ip->is_main_mem)
    {
    	 if(dvs) {
    		 cout << endl << "  Tag array: \n Total dynamic read energy/access (nJ): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<  fr->uca_q[i]->tag_array2.power.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;

    	    	cout << "Total dynamic write energy/access (nJ): ";
    	    	    	    	for (i = 0; i<dvs_levels; i++)
    	    	    	    		cout <<  fr->uca_q[i]->tag_array2.power.writeOp.dynamic * 1e9 << "; ";
    	    	    	    	cout << endl;
    	    } else {
				cout << endl << "  Tag array: \n Total dynamic read energy/access (nJ): " <<
				fr->tag_array2.power.readOp.dynamic * 1e9 << endl;
				 cout << "Total dynamic write energy/access (nJ): " <<
             fr->tag_array2.power.writeOp.dynamic * 1e9 << endl;
			}
    	 if(dvs) {
    		 cout << "\tTotal leakage read/write power of a bank (mW): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<  fr->uca_q[i]->tag_array2.power.readOp.leakage * 1e3 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\tTotal leakage read/write power of a bank (mW): " <<
				  fr->tag_array2.power.readOp.leakage * 1e3 << endl;

    	 if(dvs) {
    		 cout << "\tTotal energy in H-tree outside banks (that includes both "
    		         "address and data transfer) (nJ): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<  (fr->uca_q[i]->tag_array2.power_routing_to_bank.readOp.dynamic) * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\tTotal energy in H-tree outside banks (that includes both "
				"address and data transfer) (nJ): " <<
				  (/*fr->tag_array2.power_addr_input_htree.readOp.dynamic +
				   fr->tag_array2.power_data_output_htree.readOp.dynamic +*/
				   fr->tag_array2.power_routing_to_bank.readOp.dynamic) * 1e9 << endl;

    	 if(dvs) {
    		 cout << "\tInput H-tree inside banks Energy (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<  (fr->uca_q[i]->tag_array2.power_addr_input_htree.readOp.dynamic) * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\tInput H-tree inside banks Energy (nJ): " <<
			   (fr->tag_array2.power_addr_input_htree.readOp.dynamic) * 1e9 << endl;

    	 if(dvs) {
    		 cout << "\tOutput Htree Energy (nJ): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<   fr->uca_q[i]->tag_array2.power_data_output_htree.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\tOutput Htree Energy (nJ): " <<
				fr->tag_array2.power_data_output_htree.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tDecoder (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->tag_array2.power_row_predecoder_drivers.readOp.dynamic * 1e9 +
    	    		        fr->uca_q[i]->tag_array2.power_row_predecoder_blocks.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tDecoder (nJ): " <<
				fr->tag_array2.power_row_predecoder_drivers.readOp.dynamic * 1e9 +
				fr->tag_array2.power_row_predecoder_blocks.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tWordline (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->tag_array2.power_row_decoders.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tWordline (nJ): " <<
				fr->tag_array2.power_row_decoders.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tBitline mux & associated drivers (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
					cout <<  fr->uca_q[i]->tag_array2.power_bit_mux_predecoder_drivers.readOp.dynamic * 1e9 +
					fr->uca_q[i]->tag_array2.power_bit_mux_predecoder_blocks.readOp.dynamic * 1e9 +
					fr->uca_q[i]->tag_array2.power_bit_mux_decoders.readOp.dynamic * 1e9 << "; ";
    	    		 cout << endl;
    	    } else
			  cout <<  "\tBitline mux & associated drivers (nJ): " <<
				fr->tag_array2.power_bit_mux_predecoder_drivers.readOp.dynamic * 1e9 +
				fr->tag_array2.power_bit_mux_predecoder_blocks.readOp.dynamic * 1e9 +
				fr->tag_array2.power_bit_mux_decoders.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tSense amp mux & associated drivers (nJ): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->tag_array2.power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic * 1e9 +
			        fr->uca_q[i]->tag_array2.power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic * 1e9 +
			        fr->uca_q[i]->tag_array2.power_senseamp_mux_lev_1_decoders.readOp.dynamic * 1e9  +
			        fr->uca_q[i]->tag_array2.power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic * 1e9 +
			        fr->uca_q[i]->tag_array2.power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic * 1e9 +
			        fr->uca_q[i]->tag_array2.power_senseamp_mux_lev_2_decoders.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tSense amp mux & associated drivers (nJ): " <<
				fr->tag_array2.power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic * 1e9 +
				fr->tag_array2.power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic * 1e9 +
				fr->tag_array2.power_senseamp_mux_lev_1_decoders.readOp.dynamic * 1e9  +
				fr->tag_array2.power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic * 1e9 +
				fr->tag_array2.power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic * 1e9 +
				fr->tag_array2.power_senseamp_mux_lev_2_decoders.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tBitlines (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<  fr->uca_q[i]->tag_array2.power_bitlines.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tBitlines (nJ): " <<
				fr->tag_array2.power_bitlines.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tSense amplifier energy (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->tag_array2.power_sense_amps.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tSense amplifier energy (nJ): " <<
				fr->tag_array2.power_sense_amps.readOp.dynamic * 1e9 << endl;

    	 if(dvs) {
    		 cout <<  "\tSub-array output driver (nJ): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<   fr->uca_q[i]->tag_array2.power_output_drivers_at_subarray.readOp.dynamic * 1e9 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tSub-array output driver (nJ): " <<
				fr->tag_array2.power_output_drivers_at_subarray.readOp.dynamic * 1e9 << endl;

    	           if (dvs)
    	           {
    	        	   cout << "\tTotal leakage power in H-tree outside a bank (that includes both "
    	        			   "address and data network) without power gating((mW)): " ;
    	        	   for (i = 0; i<dvs_levels; i++)
    	        		   cout<<(fr->uca_q[i]->tag_array2.power_routing_to_bank.readOp.leakage) * 1e3 <<"; ";
        	           cout<< endl;
    	           }
    	           else
    	        	   cout << "\tTotal leakage power in H-tree outside a bank (that includes both "
    	        	       	   "address and data network) without power gating((mW)): " <<
    	        	       	  (fr->tag_array2.power_routing_to_bank.readOp.leakage) * 1e3;

    }

    cout << endl << endl <<  "Area Components:" << endl << endl;
    /* Data array area stats */
    if(dvs) {
    	cout <<  "  Data array: \n Area (mm2): ";
       	for (i = 0; i<dvs_levels; i++)
       		cout << fr->uca_q[i]->data_array2.area * 1e-6 << "; ";
       	cout << endl;
       } else
    	   cout <<  "  Data array: \n Area (mm2): " << fr->data_array2.area * 1e-6 << endl;

    if(dvs) {
    	 cout <<  "\tHeight (mm): ";
       	for (i = 0; i<dvs_levels; i++)
       		cout <<   fr->uca_q[i]->data_array2.all_banks_height*1e-3 << "; ";
       	cout << endl;
       } else
		cout <<  "\tHeight (mm): " <<
		  fr->data_array2.all_banks_height*1e-3 << endl;

    if(dvs) {
    	cout <<  "\tWidth (mm): ";
       	for (i = 0; i<dvs_levels; i++)
       		cout <<  fr->uca_q[i]->data_array2.all_banks_width*1e-3 << "; ";
       	cout << endl;
       } else
		cout <<  "\tWidth (mm): " <<
		  fr->data_array2.all_banks_width*1e-3 << endl;

    if (g_ip->print_detail) {
    	 if(dvs) {
    		 cout <<  "\tArea efficiency (Memory cell area/Total area) : ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->data_array2.area_efficiency << " %" << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tArea efficiency (Memory cell area/Total area) : " <<
				fr->data_array2.area_efficiency << " %" << endl;

    	 if(dvs) {
    		 cout << "\t\tMAT Height (mm): " ;
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->data_array2.mat_height*1e-3 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\t\tMAT Height (mm): " <<
				fr->data_array2.mat_height*1e-3 << endl;

    	 if(dvs) {
    		 cout << "\t\tMAT Length (mm): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->data_array2.mat_length*1e-3 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\t\tMAT Length (mm): " <<
				fr->data_array2.mat_length*1e-3 << endl;

    	 if(dvs) {
    		 cout << "\t\tSubarray Height (mm): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout <<  fr->uca_q[i]->data_array2.subarray_height*1e-3 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\t\tSubarray Height (mm): " <<
				fr->data_array2.subarray_height*1e-3 << endl;

    	 if(dvs) {
    		 cout << "\t\tSubarray Length (mm): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->data_array2.subarray_length*1e-3 << "; ";
    	    	cout << endl;
    	    } else
			  cout << "\t\tSubarray Length (mm): " <<
				fr->data_array2.subarray_length*1e-3 << endl;
    }

    /* Tag array area stats */
    if ((!(g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)) && !g_ip->is_main_mem)
    {
    	 if(dvs) {
    		 cout << endl << "  Tag array: \nArea (mm2): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->tag_array2.area * 1e-6 << "; ";
   	    		 cout << endl;
    	    } else
    	    	cout << endl << "  Tag array: \nArea (mm2): " << fr->tag_array2.area * 1e-6 << endl;

    	 if(dvs) {
    		 cout <<  "\tHeight (mm): " ;
			for (i = 0; i<dvs_levels; i++)
				cout << fr->uca_q[i]->tag_array2.all_banks_height*1e-3 << "; ";
			cout << endl;
    	    } else
			  cout <<  "\tHeight (mm): " <<
				fr->tag_array2.all_banks_height*1e-3 << endl;

    	 if(dvs) {
    		 cout <<  "\tWidth (mm): ";
    	    	for (i = 0; i<dvs_levels; i++)
    	    		cout << fr->uca_q[i]->tag_array2.all_banks_width*1e-3 << "; ";
    	    	cout << endl;
    	    } else
			  cout <<  "\tWidth (mm): " <<
				fr->tag_array2.all_banks_width*1e-3 << endl;

      if (g_ip->print_detail)
      {
    	  if(dvs) {
    		  cout <<  "\tArea efficiency (Memory cell area/Total area) : ";
    	     	for (i = 0; i<dvs_levels; i++)
    	     		cout <<  fr->uca_q[i]->tag_array2.area_efficiency << " %" << "; ";
    	     	cout << endl;
    	     } else
				cout <<  "\tArea efficiency (Memory cell area/Total area) : " <<
				  fr->tag_array2.area_efficiency << " %" << endl;

    	  if(dvs) {
    		  cout << "\t\tMAT Height (mm): " ;
    	     	for (i = 0; i<dvs_levels; i++)
    	     		cout <<  fr->uca_q[i]->tag_array2.mat_height*1e-3 << "; ";
    	     	cout << endl;
    	     } else
				cout << "\t\tMAT Height (mm): " <<
				  fr->tag_array2.mat_height*1e-3 << endl;

    	  if(dvs) {
    		  cout << "\t\tMAT Length (mm): " ;
    	     	for (i = 0; i<dvs_levels; i++)
    	     		cout <<  fr->uca_q[i]->tag_array2.mat_length*1e-3 << "; ";
    	     	cout << endl;
    	     } else
				cout << "\t\tMAT Length (mm): " <<
				  fr->tag_array2.mat_length*1e-3 << endl;

    	  if(dvs) {
    		  cout << "\t\tSubarray Height (mm): ";
    	     	for (i = 0; i<dvs_levels; i++)
    	     		cout <<  fr->uca_q[i]->tag_array2.subarray_height*1e-3 << "; ";
    		  cout << endl;
    	     } else
				cout << "\t\tSubarray Height (mm): " <<
				  fr->tag_array2.subarray_height*1e-3 << endl;

    	  if(dvs) {
    		  cout << "\t\tSubarray Length (mm): ";
    	     	for (i = 0; i<dvs_levels; i++)
    	     		cout << fr->uca_q[i]->tag_array2.subarray_length*1e-3 << "; ";
    	     	cout << endl;
    	     } else
				cout << "\t\tSubarray Length (mm): " <<
				  fr->tag_array2.subarray_length*1e-3 << endl;
      }
    }
    //Wire wpr; //TODO: this must change, since this changes the wire value during dvs loop.
    //Wire::print_wire();//move outside output UCA
  }
}
//Divya end

/***** Alireza - BEGIN *****/
void output_summary_of_results(uca_org_t *fr) {

  unsigned int cache_size = g_ip->cache_sz;
  string cache_size_unit = "B";
  if ( 1024 <= g_ip->cache_sz && g_ip->cache_sz < 1024*1024 ) {
    cache_size = g_ip->cache_sz / 1024;
    cache_size_unit = "KB";
  } else  if ( 1024*1024 <= g_ip->cache_sz && g_ip->cache_sz < 1024*1024*1024 ) {
    cache_size = g_ip->cache_sz / (1024*1024);
    cache_size_unit = "MB";
  }

  cout << fr->access_time*1e9 << "\t" << fr->power.readOp.dynamic*1e9 << "\t" << fr->power.writeOp.dynamic*1e9 << "\t" << fr->power.readOp.leakage*1e3 << "\t" << fr->area*1e-3*1e-3 << endl;
  
  cout << "-------------------------------------------------------------\n";
  
  cout << "---------- P-CACTI, Uniform Cache Access ----------\n";
  cout << "Cache size        : " << cache_size << cache_size_unit << endl; // unit. -Alireza
  cout << "Technology        : " << g_ip->F_sz_nm << "nm" << endl; // changed to nm. -Alireza
  cout << "Transistor type   : " << (g_ip->is_finfet ? "FinFET" : "CMOS" ) << endl; // Alireza
//  cout << "Operating voltage : " << (g_ip->is_near_threshold ? "Near-threshold" : "Super-threshold" ) << endl; // Alireza
  cout << "Operating voltage             : " << g_ip->vdd << endl; // Alireza
   if (g_ip->sram_cell_design.getType()==std_6T) { // Alireza
    cout << "SRAM cell type    : " << "Standard 6T" << endl;
  } else if (g_ip->sram_cell_design.getType()==std_8T) {
    cout << "SRAM cell type    : " << "Standard 8T" << endl;
  }
  cout << "Temperature       : " << g_ip->temp << "K" << endl; // Alireza
  if (g_ip->is_cache) {
    cout << "cache type        : " << "Cache" << endl;
  } else if (g_ip->is_main_mem) {
    cout << "cache type        : " << "Main Memory" << endl; // Alireza
  } else { // Alireza
    cout << "cache type        : " << "Scratch RAM" << endl;
  }
  
  cout << "-------------------------------------------------------------\n";
  
  cout << "Access time                           : " << fr->access_time*1e9 << " ns" << endl;
  cout << "Cycle time                            : " << fr->cycle_time*1e9 << " ns" << endl;
  if (g_ip->data_arr_ram_cell_tech_type < 4) {
    cout << "Total dynamic read energy per access  : " << fr->power.readOp.dynamic*1e9 << " nJ" << endl;
    cout << "Total dynamic write energy per access : " << fr->power.writeOp.dynamic*1e9 << " nJ" << endl;
    cout << "Total leakage power of a bank         : " << fr->power.readOp.leakage*1e3 << " mW" << endl;
  }
  cout << "Cache height x width                  : " << fr->cache_ht*1e-3 << " mm x " << fr->cache_len*1e-3 << " mm" << endl;
  cout << "Cache area                            : " << fr->area*1e-3*1e-3 << " mm2" << endl;
  
  cout << "-------------------------------------------------------------\n";

    cout << "Data Array Leakage Power Components:" << endl;
    cout << "\tTotal leakage power: " <<
        fr->data_array2.power.readOp.leakage * 1e3 << "mW" << endl;
    cout << "\tBank leakage power: " <<
        fr->data_array2.leak_power_bank * 1e3 << "mW" << endl;
    cout << "\tMat leakage power: " <<
        fr->data_array2.leak_power_mat * 1e3 << "mW" << endl;
    cout << "\tMemory array leakage power: " <<
        fr->data_array2.leak_power_mem_array * 1e3 << "mW" << endl;
    cout << "\tSRAM cell leakage power: " <<
        fr->data_array2.leak_power_sram_cell * 1e9 << "nW" << endl;

    cout << endl << "Subarray Statistics:" << endl;
    cout << "\tSubarray - Number of rows: " <<
        fr->data_array2.subarray_num_rows << endl;
    cout << "\tSubarray - Number of columns: " <<
        fr->data_array2.subarray_num_cols << endl;
    cout << "\tNumber of subarrays per Mat: " <<
        fr->data_array2.num_subarrays_per_mat << endl;
		  
  cout << "-------------------------------------------------------------\n";
  
  cout << "Best Ndwl     : " << fr->data_array2.Ndwl << endl;
  cout << "Best Ndbl     : " << fr->data_array2.Ndbl << endl;
  cout << "Best Nspd     : " << fr->data_array2.Nspd << endl;
  cout << "Best Ndcm     : " << fr->data_array2.deg_bl_muxing << endl;
  cout << "Best Ndsam L1 : " << fr->data_array2.Ndsam_lev_1 << endl;
  cout << "Best Ndsam L2 : " << fr->data_array2.Ndsam_lev_2 << endl;
  
  cout << "-------------------------------------------------------------\n";
}

void output_summary_of_results_file(uca_org_t *fr) {
  ofstream fout("pcacti_report.txt", ios::out);
  fout << "Access time                           : " << fr->access_time*1e9 << " ns" << endl;
  fout << "Cycle time                            : " << fr->cycle_time*1e9 << " ns" << endl;
  if (g_ip->data_arr_ram_cell_tech_type < 4) {
    fout << "Total dynamic read energy per access  : " << fr->power.readOp.dynamic*1e9 << " nJ" << endl;
    fout << "Total dynamic write energy per access : " << fr->power.writeOp.dynamic*1e9 << " nJ" << endl;
    fout << "Total leakage power of a bank         : " << fr->power.readOp.leakage*1e3 << " mW" << endl;
  }
  fout << "Cache height x width                  : " << fr->cache_ht*1e-3 << " mm x " << fr->cache_len*1e-3 << " mm" << endl;
  fout << "Cache area                            : " << fr->area*1e-3*1e-3 << " mm2" << endl;
  
}

/****** Alireza - END ******/

//divya adding 14-11-2021
//McPAT's plain interface, please keep !!!
uca_org_t cacti_interface(InputParameter  * const local_interface)
{
  uca_org_t fin_res;
  fin_res.valid = false;
  double Ioffs[5];

  g_ip = local_interface;
  g_ip->default_device_files();
//  cout << "io.cc::cacti_interface, techsize: " << g_ip->F_sz_um << ", wire: " << g_ip->wire_F_sz_um << ", finfet: " << g_ip->is_finfet << ", ncfet: " << g_ip->is_ncfet <<
//		  ", itrs: " << g_ip->is_itrs2012 << ", asap7: " << g_ip->is_asap7 << ", projection: " << g_ip->ic_proj_type << ", vdd: " << g_ip->vdd << endl;
//  cout << "io.cc ndbl: " << g_ip->ndbl << ", ndwl: " << g_ip->ndwl <<
//		  ", nspd: " << g_ip->nspd << ", ndcm: " << g_ip->nspd << ", sam1: " << g_ip->ndsam1 << ", sam2: " << g_ip->ndsam2 << endl;

//  cout << "is finfet: " << g_ip->is_finfet << ", vdd: " << g_ip->vdd <<  endl;
  //Divya adding 22-11-2021
  //fix the parameters for finfet and ncfet as appropriate
  if(g_ip->is_finfet && !g_ip->use_device_xml) {

	  //Fixing SRAM cells to 6T1 SRAM model
	  g_ip->sram_cell_design.setType(std_6T);
	  g_ip->Nfins[0] = 1;	// access transistor fins
	  g_ip->Nfins[1] = 1;	// pup fins
	  g_ip->Nfins[2] = 1; 	// pdn fins

	  //Dual Gate control is being set to false
	  g_ip->sram_cell_design.setDGcontrol(false);
//	  cout << "is ncfet: " << g_ip->is_ncfet << ", vdd: " << g_ip->vdd <<  endl;

	  //Fixing the transistor parameters acdng to ncfet/finfet type, instead of reading transistor.xml files
	  if(g_ip->is_ncfet) {	//for NCFET
		  g_ip->Lphys[0] = 0.02;	//20-nm access transistor
		  g_ip->Lphys[1] = 0.02;	//20-nm pup
		  g_ip->Lphys[2] = 0.02;	//20-nm pdn

		  //NCFET Ioff currents acdng to voltage
		  if(g_ip->vdd == 0.8) {
			  Ioffs[0] = 5.836957e-10;	//n-type acc transistor
			  Ioffs[1] = 6.39565e-10;	//p-type pup transistor
			  Ioffs[2] = 5.836957e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.7) {
			  Ioffs[0] = 6.880435e-10;	//n-type acc transistor
			  Ioffs[1] = 7.836957e-10;	//p-type pup transistor
			  Ioffs[2] = 6.880435e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.6) {
			  Ioffs[0] = 8.119565e-10;	//n-type acc transistor
			  Ioffs[1] = 1.0e-09;	//p-type pup transistor
			  Ioffs[2] = 8.119565e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.5) {
//			  cout << "0.5v ioff \n";
			  Ioffs[0] = 1.0e-09;		//n-type acc transistor
			  Ioffs[1] = 1.184783e-09;	//p-type pup transistor
			  Ioffs[2] = 1.0e-09;		//n-type pdn transistor
		  } else if(g_ip->vdd == 0.4) {
			  Ioffs[0] = 1.119565e-09;	//n-type acc transistor
			  Ioffs[1] = 1.456522e-09;	//p-type pup transistor
			  Ioffs[2] = 1.119565e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.3) {
			  Ioffs[0] = 1.304348e-09;	//n-type acc transistor
			  Ioffs[1] = 1.771739e-09;	//p-type pup transistor
			  Ioffs[2] = 1.304348e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.2) {
			  Ioffs[0] = 1.51087e-09;	//n-type acc transistor
			  Ioffs[1] = 2.163043e-09;	//p-type pup transistor
			  Ioffs[2] = 1.51087e-09;	//n-type pdn transistor
		  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
	  }
	  else {	//for FinFET
		  g_ip->Lphys[0] = 0.02;	//20-nm access transistor
		  g_ip->Lphys[1] = 0.02;	//20-nm pup
		  g_ip->Lphys[2] = 0.02;	//20-nm pdn

		  //FinFET Ioff currents acdng to voltage
		  if(g_ip->vdd == 0.8) {
			  Ioffs[0] = 6.684783e-09;	//n-type acc transistor
			  Ioffs[1] = 6.478261e-09;	//p-type pup transistor
			  Ioffs[2] = 6.684783e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.7) {
			  Ioffs[0] = 5.336957e-09;	//n-type acc transistor
			  Ioffs[1] = 5.130435e-09;	//p-type pup transistor
			  Ioffs[2] = 5.336957e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.6) {
			  Ioffs[0] = 4.217391e-09;	//n-type acc transistor
			  Ioffs[1] = 4.054348e-09;	//p-type pup transistor
			  Ioffs[2] = 4.217391e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.5) {
			  Ioffs[0] = 3.304348e-09;		//n-type acc transistor
			  Ioffs[1] = 3.195652e-09;	//p-type pup transistor
			  Ioffs[2] = 3.304348e-09;		//n-type pdn transistor
		  } else if(g_ip->vdd == 0.4) {
			  Ioffs[0] = 2.565217e-09;	//n-type acc transistor
			  Ioffs[1] = 2.5e-09;	//p-type pup transistor
			  Ioffs[2] = 2.565217e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.3) {
			  Ioffs[0] = 2.0e-09;	//n-type acc transistor
			  Ioffs[1] = 2.0e-09;	//p-type pup transistor
			  Ioffs[2] = 2.0e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.2) {
			  Ioffs[0] = 1.489133e-09;	//n-type acc transistor
			  Ioffs[1] = 1.532609e-09;	//p-type pup transistor
			  Ioffs[2] = 1.489133e-09;	//n-type pdn transistor
		  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
	  }
	  g_ip->sram_cell_design.setTransistorParams(g_ip->Nfins, g_ip->Lphys, Ioffs);
  }
//divya end

  if (g_ip->print_input_args)
	  g_ip->display_ip();
  if (!g_ip->error_checking()) exit(0);

//  init_tech_params(g_ip->F_sz_um, false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //Divya added wire_technology

  Wire winit; // Do not delete this line. It initializes wires.


#ifdef ENABLE_CACHE
  static DB *dbp = NULL;

  if (dbp == NULL)
  {
    char filename[1024];
    snprintf(filename, 1024, "%s/mcpat-%s.db", getenv("TMPDIR") ? getenv("TMPDIR") : "/tmp", getenv("USER"));
    db_create(&dbp, NULL, 0);
    dbp->open(dbp, NULL, filename, NULL, DB_HASH, DB_CREATE, 0);
  }

  DBT key, data;
  memset(&key, 0, sizeof(DBT));
  memset(&data, 0, sizeof(DBT));

  size_t o1 = offsetof(InputParameter, first),
         o2 = offsetof(InputParameter, last);

  // Create a clean copy of our input parameters, with zeroes on all unused locations
  InputParameter clean_ip;
  memset((char*)&clean_ip + o1, 0, o2 - o1); // Set everything to zero
  clean_ip = *g_ip; // Copies over actual (used) data

  key.data = (char*)&clean_ip + o1;
  key.size = o2 - o1;

  if (DB_NOTFOUND == dbp->get(dbp, NULL, &key, &data, 0) /* Not found in DB */
      || sizeof(fin_res) != data.size /* Or from a different version */)
  {
     solve(&fin_res);

    // If found (but size is wrong): delete it
    if (DB_NOTFOUND != dbp->get(dbp, NULL, &key, &data, 0))
      dbp->del(dbp, NULL, &key, 0);

    data.data = &fin_res;
    data.size = sizeof(fin_res);
    int res = dbp->put(dbp, NULL, &key, &data, DB_NOOVERWRITE);
    if (res)
      printf("DB write error: %d\n", res);
    dbp->sync(dbp, 0);
  }
  else
  {
    assert(sizeof(fin_res) == data.size);
    memcpy(&fin_res, data.data, sizeof(fin_res));
  }
#else
  solve(&fin_res);
#endif

//  if (g_ip->is_dvs)
  if (!g_ip->dvs_voltage.empty())
  {
	  update_dvs(&fin_res);
  }

  return fin_res;
}

//McPAT's plain interface, please keep !!!
uca_org_t init_interface(InputParameter* const local_interface)
{
  uca_org_t fin_res;
  fin_res.valid = false;
  double Ioffs[5];

  g_ip = local_interface;
  g_ip->default_device_files();

  //Divya adding 22-11-2021
  //fix the parameters for finfet and ncfet as appropriate
  if(g_ip->is_finfet && !g_ip->use_device_xml) {
	  //Fixing SRAM cells to 6T1 SRAM model
	  g_ip->sram_cell_design.setType(std_6T);
	  g_ip->Nfins[0] = 1;	// access transistor fins
	  g_ip->Nfins[1] = 1;	// pup fins
	  g_ip->Nfins[2] = 1; 	// pdn fins

	  //Dual Gate control is being set to false
	  g_ip->sram_cell_design.setDGcontrol(false);

	  //Fixing the transistor parameters acdng to ncfet/finfet type, instead of reading transistor.xml files
	  if(g_ip->is_ncfet) {	//for NCFET
		  g_ip->Lphys[0] = 0.02;	//20-nm access transistor
		  g_ip->Lphys[1] = 0.02;	//20-nm pup
		  g_ip->Lphys[2] = 0.02;	//20-nm pdn

		  //NCFET Ioff currents acdng to voltage
		  if(g_ip->vdd == 0.8) {
			  Ioffs[0] = 5.836957e-10;	//n-type acc transistor
			  Ioffs[1] = 6.39565e-10;	//p-type pup transistor
			  Ioffs[2] = 5.836957e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.7) {
			  Ioffs[0] = 6.880435e-10;	//n-type acc transistor
			  Ioffs[1] = 7.836957e-10;	//p-type pup transistor
			  Ioffs[2] = 6.880435e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.6) {
			  Ioffs[0] = 8.119565e-10;	//n-type acc transistor
			  Ioffs[1] = 1.0e-09;	//p-type pup transistor
			  Ioffs[2] = 8.119565e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.5) {
			  Ioffs[0] = 1.0e-09;		//n-type acc transistor
			  Ioffs[1] = 1.184783e-09;	//p-type pup transistor
			  Ioffs[2] = 1.0e-09;		//n-type pdn transistor
		  } else if(g_ip->vdd == 0.4) {
			  Ioffs[0] = 1.119565e-09;	//n-type acc transistor
			  Ioffs[1] = 1.456522e-09;	//p-type pup transistor
			  Ioffs[2] = 1.119565e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.3) {
			  Ioffs[0] = 1.304348e-09;	//n-type acc transistor
			  Ioffs[1] = 1.771739e-09;	//p-type pup transistor
			  Ioffs[2] = 1.304348e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.2) {
			  Ioffs[0] = 1.51087e-09;	//n-type acc transistor
			  Ioffs[1] = 2.163043e-09;	//p-type pup transistor
			  Ioffs[2] = 1.51087e-09;	//n-type pdn transistor
		  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
	  }
	  else {	//for FinFET
		  g_ip->Lphys[0] = 0.02;	//20-nm access transistor
		  g_ip->Lphys[1] = 0.02;	//20-nm pup
		  g_ip->Lphys[2] = 0.02;	//20-nm pdn

		  //FinFET Ioff currents acdng to voltage
		  if(g_ip->vdd == 0.8) {
			  Ioffs[0] = 6.684783e-09;	//n-type acc transistor
			  Ioffs[1] = 6.478261e-09;	//p-type pup transistor
			  Ioffs[2] = 6.684783e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.7) {
			  Ioffs[0] = 5.336957e-09;	//n-type acc transistor
			  Ioffs[1] = 5.130435e-09;	//p-type pup transistor
			  Ioffs[2] = 5.336957e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.6) {
			  Ioffs[0] = 4.217391e-09;	//n-type acc transistor
			  Ioffs[1] = 4.054348e-09;	//p-type pup transistor
			  Ioffs[2] = 4.217391e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.5) {
			  Ioffs[0] = 3.304348e-09;		//n-type acc transistor
			  Ioffs[1] = 3.195652e-09;	//p-type pup transistor
			  Ioffs[2] = 3.304348e-09;		//n-type pdn transistor
		  } else if(g_ip->vdd == 0.4) {
			  Ioffs[0] = 2.565217e-09;	//n-type acc transistor
			  Ioffs[1] = 2.5e-09;	//p-type pup transistor
			  Ioffs[2] = 2.565217e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.3) {
			  Ioffs[0] = 2.0e-09;	//n-type acc transistor
			  Ioffs[1] = 2.0e-09;	//p-type pup transistor
			  Ioffs[2] = 2.0e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.2) {
			  Ioffs[0] = 1.489133e-09;	//n-type acc transistor
			  Ioffs[1] = 1.532609e-09;	//p-type pup transistor
			  Ioffs[2] = 1.489133e-09;	//n-type pdn transistor
		  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
	  }
	  g_ip->sram_cell_design.setTransistorParams(g_ip->Nfins, g_ip->Lphys, Ioffs);

	//divya end
  }
  g_ip->error_checking();

//  cout << "io.cc::init_interface, techsize: " << g_ip->F_sz_um << ", wire: " << g_ip->wire_F_sz_um << ", finfet: " << g_ip->is_finfet << ", ncfet: " << g_ip->is_ncfet <<
//		  ", itrs: " << g_ip->is_itrs2012 << ", asap7: " << g_ip->is_asap7 << ", projection: " << g_ip->ic_proj_type << ", vdd: " << g_ip->vdd << endl;

  //  init_tech_params(g_ip->F_sz_um, false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //Divya added wire_technology
  Wire winit; // Do not delete this line. It initializes wires.

  return fin_res;
}


void reconfigure(InputParameter *local_interface, uca_org_t *fin_res)
{
	double Ioffs[5];

  // Copy the InputParameter to global interface (g_ip) and do error checking.
  g_ip = local_interface;
  g_ip->default_device_files();
  cout << "io.cc::reconfigure, techsize: " << g_ip->F_sz_um << ", wire: " << g_ip->wire_F_sz_um << ", finfet: " << g_ip->is_finfet << ", ncfet: " << g_ip->is_ncfet <<
		  ", itrs: " << g_ip->is_itrs2012 << ", asap7: " << g_ip->is_asap7 << ", projection: " << g_ip->ic_proj_type << ", vdd: " << g_ip->vdd << endl;

  if(g_ip->is_finfet && !g_ip->use_device_xml) {
  //Divya adding 22-11-2021
  //fix the parameters for finfet and ncfet as appropriate

	  //Fixing SRAM cells to 6T1 SRAM model
	  g_ip->sram_cell_design.setType(std_6T);
	  g_ip->Nfins[0] = 1;	// access transistor fins
	  g_ip->Nfins[1] = 1;	// pup fins
	  g_ip->Nfins[2] = 1; 	// pdn fins

	  //Dual Gate control is being set to false
	  g_ip->sram_cell_design.setDGcontrol(false);

	  //Fixing the transistor parameters acdng to ncfet/finfet type, instead of reading transistor.xml files
	  if(g_ip->is_ncfet) {	//for NCFET
		  g_ip->Lphys[0] = 0.02;	//20-nm access transistor
		  g_ip->Lphys[1] = 0.02;	//20-nm pup
		  g_ip->Lphys[2] = 0.02;	//20-nm pdn

		  //NCFET Ioff currents acdng to voltage
		  if(g_ip->vdd == 0.8) {
			  Ioffs[0] = 5.836957e-10;	//n-type acc transistor
			  Ioffs[1] = 6.39565e-10;	//p-type pup transistor
			  Ioffs[2] = 5.836957e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.7) {
			  Ioffs[0] = 6.880435e-10;	//n-type acc transistor
			  Ioffs[1] = 7.836957e-10;	//p-type pup transistor
			  Ioffs[2] = 6.880435e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.6) {
			  Ioffs[0] = 8.119565e-10;	//n-type acc transistor
			  Ioffs[1] = 1.0e-09;	//p-type pup transistor
			  Ioffs[2] = 8.119565e-10;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.5) {
			  Ioffs[0] = 1.0e-09;		//n-type acc transistor
			  Ioffs[1] = 1.184783e-09;	//p-type pup transistor
			  Ioffs[2] = 1.0e-09;		//n-type pdn transistor
		  } else if(g_ip->vdd == 0.4) {
			  Ioffs[0] = 1.119565e-09;	//n-type acc transistor
			  Ioffs[1] = 1.456522e-09;	//p-type pup transistor
			  Ioffs[2] = 1.119565e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.3) {
			  Ioffs[0] = 1.304348e-09;	//n-type acc transistor
			  Ioffs[1] = 1.771739e-09;	//p-type pup transistor
			  Ioffs[2] = 1.304348e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.2) {
			  Ioffs[0] = 1.51087e-09;	//n-type acc transistor
			  Ioffs[1] = 2.163043e-09;	//p-type pup transistor
			  Ioffs[2] = 1.51087e-09;	//n-type pdn transistor
		  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
	  }
	  else {	//for FinFET
		  g_ip->Lphys[0] = 0.02;	//20-nm access transistor
		  g_ip->Lphys[1] = 0.02;	//20-nm pup
		  g_ip->Lphys[2] = 0.02;	//20-nm pdn

		  //FinFET Ioff currents acdng to voltage
		  if(g_ip->vdd == 0.8) {
			  Ioffs[0] = 6.684783e-09;	//n-type acc transistor
			  Ioffs[1] = 6.478261e-09;	//p-type pup transistor
			  Ioffs[2] = 6.684783e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.7) {
			  Ioffs[0] = 5.336957e-09;	//n-type acc transistor
			  Ioffs[1] = 5.130435e-09;	//p-type pup transistor
			  Ioffs[2] = 5.336957e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.6) {
			  Ioffs[0] = 4.217391e-09;	//n-type acc transistor
			  Ioffs[1] = 4.054348e-09;	//p-type pup transistor
			  Ioffs[2] = 4.217391e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.5) {
			  Ioffs[0] = 3.304348e-09;		//n-type acc transistor
			  Ioffs[1] = 3.195652e-09;	//p-type pup transistor
			  Ioffs[2] = 3.304348e-09;		//n-type pdn transistor
		  } else if(g_ip->vdd == 0.4) {
			  Ioffs[0] = 2.565217e-09;	//n-type acc transistor
			  Ioffs[1] = 2.5e-09;	//p-type pup transistor
			  Ioffs[2] = 2.565217e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.3) {
			  Ioffs[0] = 2.0e-09;	//n-type acc transistor
			  Ioffs[1] = 2.0e-09;	//p-type pup transistor
			  Ioffs[2] = 2.0e-09;	//n-type pdn transistor
		  } else if(g_ip->vdd == 0.2) {
			  Ioffs[0] = 1.489133e-09;	//n-type acc transistor
			  Ioffs[1] = 1.532609e-09;	//p-type pup transistor
			  Ioffs[2] = 1.489133e-09;	//n-type pdn transistor
		  } else
				cerr << "ERROR: Invalid transistor type!\nSupported transistor types: 'finfet', 'cmos'.\n";
	  }
	  g_ip->sram_cell_design.setTransistorParams(g_ip->Nfins, g_ip->Lphys, Ioffs);

	  g_ip->F_sz_um 		= 0.014;	//14-nm in um
	  g_ip->wire_F_sz_um 	= 0.007;	//7nm in um
	  g_ip->is_asap7		= true;
	  g_ip->ic_proj_type	= 0;		//0 for aggressive
  }
  //divya end

  g_ip->error_checking();

  // Initialize technology parameters
//  init_tech_params(g_ip->F_sz_um,false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //Divya added wire_technology

  Wire winit; // Do not delete this line. It initializes wires.

  // This corresponds to solve() in the initialization process.
  update_dvs(fin_res);
}
//divya adding end

