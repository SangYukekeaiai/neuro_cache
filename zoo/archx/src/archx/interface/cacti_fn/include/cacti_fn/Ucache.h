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

#ifndef __UCACHE_H__
#define __UCACHE_H__

#include <list>
#include "area.h"
#include "router.h"
#include "nuca.h"
#include "uca.h"
 

struct solution
{
  int    tag_array_index;
  int    data_array_index;
  list<mem_array *>::iterator tag_array_iter;
  list<mem_array *>::iterator data_array_iter;
  double access_time;
  double cycle_time;
  double area;
  double efficiency;
  powerDef total_power;
};

bool calculate_time(
    bool is_tag,
    int pure_ram,
    bool pure_cam,
    double Nspd,
    unsigned int Ndwl, 
    unsigned int Ndbl,
    unsigned int Ndcm,
    unsigned int Ndsam_lev_1,
    unsigned int Ndsam_lev_2,
    mem_array *ptr_array,
    int flag_results_populate,
    results_mem_array *ptr_results,
    uca_org_t *ptr_fin_res,
    bool is_main_mem);

//Divya added 11-11-2020
void collect_uca_results(
    double Nspd,
    unsigned int Ndwl,
    unsigned int Ndbl,
    unsigned int Ndcm,
    unsigned int Ndsam_lev_1,
    unsigned int Ndsam_lev_2,
    UCA const * const uca,
    mem_array * const ptr_array,
    bool is_main_mem);

void update_dvs(uca_org_t *fin_res);
//Divya end

void solve(uca_org_t *fin_res);
//void init_tech_params(double tech, bool is_tag);
void init_tech_params(double tech, double wire_tech, bool is_tag); //divya added wire technology


struct calc_time_mt_wrapper_struct
{
  uint32_t tid;
  bool     is_tag;
  bool     pure_ram;
  bool     pure_cam;
  bool     is_main_mem;
  double   Nspd_min;

  min_values_t * data_res;
  min_values_t * tag_res;

  list<mem_array *> data_arr;
  list<mem_array *> tag_arr;
};

void *calc_time_mt_wrapper(void * void_obj);

#endif
