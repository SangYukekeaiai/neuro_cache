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

#include <time.h>
#include <math.h>


#include "area.h"
#include "basic_circuit.h"
#include "component.h"
#include "const.h"
#include "parameter.h"
#include "cacti_interface.h"
#include "Ucache.h"

#include <pthread.h>
#include <iostream>
#include <algorithm>

using namespace std;



/***** Alireza2 - BEGIN *****/
void SRAMCellParameters::setTransistorParams(
       int Nfins[5], double Lphys[5], double Ioffs[5]) {
  acc.Nfin = Nfins[0];
  pup.Nfin = Nfins[1];
  pdn.Nfin = Nfins[2];
  iso.Nfin = Nfins[3];
  rac.Nfin = Nfins[4];
  acc.Lphy = Lphys[0];
  pup.Lphy = Lphys[1];
  pdn.Lphy = Lphys[2];
  iso.Lphy = Lphys[3];
  rac.Lphy = Lphys[4];
  acc.Ioff = Ioffs[0];
  pup.Ioff = Ioffs[1];
  pdn.Ioff = Ioffs[2];
  iso.Ioff = Ioffs[3];
  rac.Ioff = Ioffs[4];
 // cout << "accoff  : " << acc.Ioff << ", pupOff : " << pup.Ioff << ", pdnoff : " << pdn.Ioff << endl;
}

void SRAMCellParameters::getNfins(int (&n)[5]) {
  n[0] = acc.Nfin;
  n[1] = pup.Nfin;
  n[2] = pdn.Nfin;
  n[3] = iso.Nfin;
  n[4] = rac.Nfin;
}

double SRAMCellParameters::calc_height(double lambda_um) {
  if (g_ip->is_finfet) {
    if ( g_ip->sram_cell_design.getType() == std_6T ) {
      height = 2*MAX(acc.Lphy, MAX(pup.Lphy, pdn.Lphy))
             + ((4*W_G2C)+(2*W_C))*lambda_um;
    } else if ( g_ip->sram_cell_design.getType() == std_8T ) {
      height = MAX(MAX(acc.Lphy, iso.Lphy), MAX(pup.Lphy, pdn.Lphy))
             + MAX(MAX(acc.Lphy, rac.Lphy), MAX(pup.Lphy, pdn.Lphy))
             + ((4*W_G2C)+(2*W_C))*lambda_um;
    } else {
      cout << "ERROR: Invalid SRAM cell type in 'calc_height' function!\n";
      exit(0);
    }
  } else {
    cout << "ERROR: Planar CMOS devices are not supported by 'calc_height' function!\n";
    exit(0);
  }
  return height;
}

double SRAMCellParameters::calc_width(double lambda_um, double p_fin, double t_si) {
  if (g_ip->is_finfet) {
    double Wx = (W_G2C+W_GbF-(W_C/2))*lambda_um + (t_si/2);
	 double Wpfin;
    if ( g_ip->sram_cell_design.getType() == std_6T ) {
      Wpfin = p_fin * (2*(pdn.Nfin-1) + 2*(MAX(pup.Nfin,acc.Nfin)-1));
      if (!dg_control && pdn.Nfin==1 && pup.Nfin==1 ) {
        width = Wpfin + (2*Wx) + ((5*W_C)+(3*W_M2M))*lambda_um;
      } else {
        width = Wpfin + ((5*W_C)+(5*W_M2M))*lambda_um;
      }
    } else if ( g_ip->sram_cell_design.getType() == std_8T ) {
      Wpfin = p_fin * (2*(pdn.Nfin-1) + 2*(MAX(pup.Nfin,acc.Nfin)-1)
		                                + 2*(MAX(rac.Nfin,iso.Nfin)-1));
      if (!dg_control ) {
        if (pdn.Nfin==1 && pup.Nfin==1 ) {
          width = Wpfin + (3*Wx) + ((7*W_C)+(4*W_M2M))*lambda_um;
        } else {
          width = Wpfin + ((7*W_C)+(7*W_M2M))*lambda_um;
        }
      } else {
        if (pdn.Nfin==1 && pup.Nfin==1 ) {
          width = Wpfin + (2*Wx) + ((5.5*W_C)+(3*W_M2M)+W_G2F+W_G2C+W_G2G)*lambda_um
                + t_si + pup.Lphy + (iso.Lphy/2);
        } else {
          width = Wpfin + ((5.5*W_C)+(5*W_M2M)+W_G2F+W_G2C+W_G2G)*lambda_um
                + t_si + pup.Lphy + (iso.Lphy/2);
        }
      }
    } else {
      cout << "ERROR: Invalid SRAM cell type in 'calc_width' function!\n";
      exit(0);
    }
  } else {
    cout << "ERROR: Planar CMOS devices are not supported by 'calc_width' function!\n";
    exit(0);
  }
  return width;
}

// double SRAMCellParameters::getPleakAccTx(double vdd, double hfin)
double SRAMCellParameters::getPleakAccTx(double vdd, double hfin, double wfin) {
  if ( PleakAT_given ) {
    return Pleak_acctx;
  } else {
    if (g_ip->is_finfet) {
 //     return ((acc.Nfin*acc.Ioff) * 2 * hfin * vdd);
 		return ((acc.Nfin*acc.Ioff) * (2 * hfin + wfin) * vdd);
     } else {
//      double Iport = cmos_Ileak(g_tp.sram.cell_a_w, 0,  false, true);
    	 double Iport     = cmos_Isub_leakage(g_tp.cam.cell_a_w, 0,  1, nmos, false, true);//TODO: how much is the idle time? just by *2?
      return (Iport * vdd);
    }
  }
}


// double SRAMCellParameters::getPleakCCInv(double vdd, double hfin)
double SRAMCellParameters::getPleakCCInv(double vdd, double hfin, double wfin) {
  if ( PleakCC_given ) {
    return Pleak_ccinv;
  } else {
    if (g_ip->is_finfet) {
 //     return (((pup.Nfin*pup.Ioff)+(pdn.Nfin*pdn.Ioff)) * 2 * hfin * vdd);
 		return (((pup.Nfin*pup.Ioff)+(pdn.Nfin*pdn.Ioff)) * (2 * hfin + wfin) * vdd);
    } else {
//      double Icell = cmos_Ileak(g_tp.sram.cell_nmos_w, g_tp.sram.cell_pmos_w, false, true);
    	double Icell     = cmos_Isub_leakage(g_tp.cam.cell_nmos_w, g_tp.cam.cell_pmos_w, 1, inv, false, true)*2;
      return (Icell * vdd);
    }
  }
}

void SRAMCellParameters::print_transistor_params() {
	cout << "SRAM cell transistor parameters:\n";
	cout << "Access transistor:      Nfin=" << acc.Nfin << ", Lphy=" << acc.Lphy << ", Ioff=" << acc.Ioff << endl;
	cout << "Pull up transistor:     Nfin=" << pup.Nfin << ", Lphy=" << pup.Lphy << ", Ioff=" << pup.Ioff << endl;
	cout << "Pull down transistor:   Nfin=" << pdn.Nfin << ", Lphy=" << pdn.Lphy << ", Ioff=" << pdn.Ioff << endl;
	if ( g_ip->sram_cell_design.getType() == std_8T ) {
		cout << "Isolator transistor:    Nfin=" << iso.Nfin << ", Lphy=" << iso.Lphy << ", Ioff=" << iso.Ioff << endl;
		cout << "Read access transistor: Nfin=" << rac.Nfin << ", Lphy=" << rac.Lphy << ", Ioff=" << rac.Ioff << endl;
	}
}
/****** Alireza2 - END ******/



bool mem_array::lt(const mem_array * m1, const mem_array * m2)
{
  if (m1->Nspd < m2->Nspd) return true;
  else if (m1->Nspd > m2->Nspd) return false;
  else if (m1->Ndwl < m2->Ndwl) return true;
  else if (m1->Ndwl > m2->Ndwl) return false;
  else if (m1->Ndbl < m2->Ndbl) return true;
  else if (m1->Ndbl > m2->Ndbl) return false;
  else if (m1->deg_bl_muxing < m2->deg_bl_muxing) return true;
  else if (m1->deg_bl_muxing > m2->deg_bl_muxing) return false;
  else if (m1->Ndsam_lev_1 < m2->Ndsam_lev_1) return true;
  else if (m1->Ndsam_lev_1 > m2->Ndsam_lev_1) return false;
  else if (m1->Ndsam_lev_2 < m2->Ndsam_lev_2) return true;
  else return false;
}



void uca_org_t::find_delay()
{
  mem_array & data_arr = data_array2;
  mem_array & tag_arr  = tag_array2;

  // check whether it is a regular cache or scratch ram
//  if (g_ip->is_cache == false)
  if (g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)
  {
    access_time = data_arr.access_time;
  }
  // Both tag and data lookup happen in parallel
  // and the entire set is sent over the data array h-tree without
  // waiting for the way-select signal --TODO add the corresponding
  // power overhead Nav
  else if (g_ip->fast_access == true)
  {
    access_time = MAX(tag_arr.access_time, data_arr.access_time);
  }
  // Tag is accessed first. On a hit, way-select signal along with the
  // address is sent to read/write the appropriate block in the data
  // array
  else if (g_ip->is_seq_acc == true)
  {
    access_time = tag_arr.access_time + data_arr.access_time;
  }
  // Normal access: tag array access and data array access happen in parallel.
  // But, the data array will wait for the way-select and transfer only the
  // appropriate block over the h-tree.
  else
  {
    access_time = MAX(tag_arr.access_time + data_arr.delay_senseamp_mux_decoder,
                      data_arr.delay_before_subarray_output_driver) +
                  data_arr.delay_from_subarray_output_driver_to_output;
  }
}



void uca_org_t::find_energy()
{
//  if (g_ip->is_cache)
  if (!(g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc))//(g_ip->is_cache)
	power = data_array2.power + tag_array2.power;
  else 
    power = data_array2.power;
}



void uca_org_t::find_area()
{
//  if (g_ip->is_cache == false)
  if (g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)//(g_ip->is_cache == false)
  {
    cache_ht  = data_array2.height;
    cache_len = data_array2.width;
  }
  else
  {
    cache_ht  = MAX(tag_array2.height, data_array2.height);
    cache_len = tag_array2.width + data_array2.width;
  }
  area = cache_ht * cache_len;
}

void uca_org_t::adjust_area()
{
  double area_adjust;
  if (g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc)
  {
    if (data_array2.area_efficiency/100.0<0.2)
    {
    	//area_adjust = sqrt(area/(area*(data_array2.area_efficiency/100.0)/0.2));
    	area_adjust = sqrt(0.2/(data_array2.area_efficiency/100.0));
    	cache_ht  = cache_ht/area_adjust;
    	cache_len = cache_len/area_adjust;
    }
  }
  area = cache_ht * cache_len;
}

void uca_org_t::find_cyc()
{
//  if (g_ip->is_cache == false)
  if ((g_ip->pure_ram|| g_ip->pure_cam || g_ip->fully_assoc))//(g_ip->is_cache == false)
  {
    cycle_time = data_array2.cycle_time;
  }
  else
  {
    cycle_time = MAX(tag_array2.cycle_time,
                    data_array2.cycle_time);
  }
}

//Divya added 11-11-2020
uca_org_t :: uca_org_t()
//:tag_array2(0),
 //data_array2(0)
{
	uca_q = vector<uca_org_t * >(0);
}

void uca_org_t :: cleanup()
{
	//	uca_org_t * it_uca_org;
/*	if (data_array2!=0){
		delete data_array2;
		data_array2 =0;
	}

	if (tag_array2!=0){
		delete tag_array2;
		tag_array2 =0;
	}
*/
	std::vector<uca_org_t * >::size_type sz = uca_q.size();
	for (int i=sz-1; i>=0; i--)
	{
/*		if (uca_q[i]->data_array2!=0)
		{
			delete uca_q[i]->data_array2;
			uca_q[i]->data_array2 =0;
		}
		if (uca_q[i]->tag_array2!=0){
			delete uca_q[i]->tag_array2;
			uca_q[i]->tag_array2 =0;
		}
*/
		delete uca_q[i];
		uca_q[i] =0;
		uca_q.pop_back();
	}
}
//Divya end
